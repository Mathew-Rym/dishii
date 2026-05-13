# agent_automation.py - Complete Background AI Agent
import os
import sys
from datetime import datetime, date, timedelta
import pandas as pd
from supabase import create_client
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json

load_dotenv()

# Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "")

# Initialize Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============================================
# CONFIGURATION
# ============================================
RED_THRESHOLD = 60
AMBER_THRESHOLD = 120
STOCK_WARNING_DAYS = 14

# ============================================
# HELPER FUNCTIONS
# ============================================

def log_automation(job_name, status, records_processed=0, error=None):
    """Log automation runs to database"""
    try:
        supabase.table("automation_logs").insert({
            "job_name": job_name,
            "status": status,
            "records_processed": records_processed,
            "error_message": error,
            "started_at": datetime.now().isoformat(),
            "completed_at": datetime.now().isoformat()
        }).execute()
    except:
        pass

def send_email_alert(subject, body):
    """Send email alert (free via Gmail SMTP)"""
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        print(f"[EMAIL] Would send: {subject}")
        return
    
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = ALERT_EMAIL
        msg['Subject'] = f"[Dishii AI] {subject}"
        
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"[EMAIL] Sent: {subject}")
    except Exception as e:
        print(f"[EMAIL] Failed: {e}")

def get_traffic_light(days_left):
    """Determine traffic light status"""
    if days_left is None:
        return "⚪", "Unknown"
    if days_left < 0:
        return "🔴", "Expired"
    if days_left <= RED_THRESHOLD:
        return "🔴", "Critical"
    if days_left <= AMBER_THRESHOLD:
        return "🟠", "Monitor"
    return "🟢", "Healthy"

# ============================================
# CORE AUTOMATION FUNCTIONS
# ============================================

def update_all_inventory_expiry():
    """Update expiry dates for all products (runs daily)"""
    print(f"[{datetime.now()}] Updating inventory expiry dates...")
    
    # Get all inventory items
    items = supabase.table("inventory_items").select("*").execute()
    updated_count = 0
    
    for item in items.data:
        expiry_date = item.get("expiry_date")
        if expiry_date:
            try:
                expiry = pd.to_datetime(expiry_date).date()
                days_left = (expiry - date.today()).days
                
                # Get traffic light
                traffic_light, status = get_traffic_light(days_left)
                
                # Update in database
                supabase.table("inventory_items").update({
                    "days_to_expiry": days_left,
                    "traffic_light": traffic_light,
                    "traffic_status": status,
                    "updated_at": datetime.now().isoformat()
                }).eq("id", item["id"]).execute()
                updated_count += 1
            except:
                pass
    
    print(f"✅ Updated {updated_count} items")
    log_automation("update_expiry", "success", updated_count)
    return updated_count

def save_daily_snapshot():
    """Save current state to history (for learning)"""
    print(f"[{datetime.now()}] Saving daily snapshot...")
    
    items = supabase.table("inventory_items").select("*").execute()
    history_records = []
    
    for item in items.data:
        history_records.append({
            "sku": item.get("sku"),
            "product_name": item.get("product_name"),
            "current_stock": item.get("current_stock"),
            "days_to_expiry": item.get("days_to_expiry"),
            "traffic_light": item.get("traffic_light"),
            "status": item.get("traffic_status"),
            "snapshot_date": date.today().isoformat()
        })
    
    if history_records:
        supabase.table("inventory_history").insert(history_records).execute()
        print(f"✅ Saved {len(history_records)} records to history")
        log_automation("daily_snapshot", "success", len(history_records))
    
    return len(history_records)

def detect_critical_items():
    """Find items that need immediate action"""
    print(f"[{datetime.now()}] Checking for critical items...")
    
    # Get critical items (red traffic light or low stock)
    critical = supabase.table("inventory_items").select("*").eq("traffic_light", "🔴").execute()
    low_stock = supabase.table("inventory_items").select("*").lt("current_stock", 50).execute()
    
    all_critical = []
    seen = set()
    
    for item in critical.data:
        if item["product_name"] not in seen:
            all_critical.append(item)
            seen.add(item["product_name"])
    
    for item in low_stock.data:
        if item["product_name"] not in seen:
            all_critical.append(item)
            seen.add(item["product_name"])
    
    print(f"⚠️ Found {len(all_critical)} critical items")
    log_automation("detect_critical", "success", len(all_critical))
    
    return all_critical

def generate_ai_alerts(critical_items):
    """Use Gemini to generate smart alerts"""
    if not critical_items:
        return None
    
    try:
        from google import genai
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        
        products_list = "\n".join([f"- {i['product_name']}: {i.get('current_stock', 0)} units, {i.get('days_to_expiry', 0)} days to expiry" for i in critical_items[:10]])
        
        prompt = f"""
        You are Dishii AI, an automated inventory agent.
        
        The following products need immediate attention:
        {products_list}
        
        Generate a concise alert message (max 200 words) with:
        1. Summary of the situation
        2. Top 3 priority actions
        3. Recommended next steps
        
        Be urgent but professional.
        """
        
        response = client.models.generate_content(
            model="models/gemini-2.0-flash",
            contents=prompt
        )
        
        return response.text
    except Exception as e:
        return f"Critical: {len(critical_items)} products need immediate attention. Review dashboard for details."

def send_alerts(critical_items, ai_message):
    """Send alerts via email"""
    if not critical_items:
        return
    
    # Create HTML email
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; }}
            .critical {{ color: #dc2626; }}
            .alert-box {{ background: #fee2e2; padding: 15px; border-radius: 10px; }}
            table {{ border-collapse: collapse; width: 100%; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        </style>
    </head>
    <body>
        <h2>🚨 Dishii AI Daily Alert</h2>
        <p><strong>Date:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        
        <div class="alert-box">
            <h3>Critical Items: {len(critical_items)}</h3>
            <p>{ai_message if ai_message else 'Immediate action required.'}</p>
        </div>
        
        <h3>Products Requiring Attention</h3>
        <table>
            <tr><th>Product</th><th>Stock</th><th>Days to Expiry</th><th>Status</th></tr>
            {''.join([f"<tr><td>{i['product_name']}</td><td>{i.get('current_stock', 0)}</td><td>{i.get('days_to_expiry', 'N/A')}</td><td class='critical'>CRITICAL</td></tr>" for i in critical_items[:15]])}
        </table>
        
        <p><small>Dishii AI - Automated Inventory Intelligence</small></p>
    </body>
    </html>
    """
    
    send_email_alert(f"Daily Alert - {len(critical_items)} Critical Items", html)
    print(f"📧 Sent alert email for {len(critical_items)} items")

def calculate_learned_trends():
    """Learn from historical data to improve recommendations"""
    print(f"[{datetime.now()}] Calculating learned trends...")
    
    # Get last 30 days of history
    cutoff_date = (date.today() - timedelta(days=30)).isoformat()
    history = supabase.table("inventory_history").select("*").gte("snapshot_date", cutoff_date).execute()
    
    if not history.data:
        print("Not enough history data (need 30+ days)")
        return
    
    df = pd.DataFrame(history.data)
    
    # Group by product and calculate trends
    for product_name, group in df.groupby("product_name"):
        if len(group) >= 7:  # Need at least 7 days of data
            # Calculate metrics
            avg_stock = group["current_stock"].mean()
            min_stock = group["current_stock"].min()
            max_stock = group["current_stock"].max()
            avg_expiry = group["days_to_expiry"].mean() if "days_to_expiry" in group else 0
            
            # Calculate waste rate (how often stock decreases rapidly)
            stock_changes = group["current_stock"].diff().dropna()
            waste_events = len(stock_changes[stock_changes < -50])  # Drop of 50+ units
            waste_rate = (waste_events / len(stock_changes)) * 100 if len(stock_changes) > 0 else 0
            
            # Suggest optimal discount based on waste rate
            if waste_rate > 30:
                optimal_discount = 50
            elif waste_rate > 15:
                optimal_discount = 30
            else:
                optimal_discount = 10
            
            # Confidence increases with more data
            confidence = min(100, len(group) * 3)
            
            # Save or update trends
            supabase.table("product_trends").upsert({
                "product_name": product_name,
                "avg_stock": round(avg_stock, 2),
                "min_stock": round(min_stock, 2),
                "max_stock": round(max_stock, 2),
                "avg_expiry_days": round(avg_expiry, 2) if avg_expiry else None,
                "waste_rate": round(waste_rate, 2),
                "optimal_discount": optimal_discount,
                "confidence_score": confidence,
                "updated_at": datetime.now().isoformat()
            }).execute()
    
    print(f"✅ Calculated trends for products")
    log_automation("calculate_trends", "success")

def generate_daily_report():
    """Generate and send daily summary report"""
    print(f"[{datetime.now()}] Generating daily report...")
    
    # Get summary stats
    items = supabase.table("inventory_items").select("*").execute()
    critical = [i for i in items.data if i.get("traffic_light") == "🔴"]
    monitor = [i for i in items.data if i.get("traffic_light") == "🟠"]
    healthy = [i for i in items.data if i.get("traffic_light") == "🟢"]
    
    total_value = sum([i.get("current_stock", 0) * i.get("selling_price", 0) for i in items.data])
    
    report_html = f"""
    <html>
    <head><style>
        body {{ font-family: Arial; }}
        .kpi {{ display: inline-block; width: 200px; padding: 15px; margin: 10px; background: #f0f0f0; border-radius: 10px; }}
        .value {{ font-size: 24px; font-weight: bold; }}
        .red {{ color: #dc2626; }}
        .amber {{ color: #f59e0b; }}
        .green {{ color: #10b981; }}
    </style></head>
    <body>
        <h2>📊 Dishii Daily Operations Report</h2>
        <p><strong>Date:</strong> {datetime.now().strftime('%Y-%m-%d')}</p>
        
        <div>
            <div class="kpi"><div class="value">{len(items.data)}</div>Total Products</div>
            <div class="kpi"><div class="value red">{len(critical)}</div>Critical (Red)</div>
            <div class="kpi"><div class="value amber">{len(monitor)}</div>Monitor (Amber)</div>
            <div class="kpi"><div class="value green">{len(healthy)}</div>Healthy (Green)</div>
            <div class="kpi"><div class="value">KES {total_value:,.0f}</div>Inventory Value</div>
        </div>
        
        <h3>Recommendations</h3>
        <ul>
            <li>📦 Order required for {len([i for i in items.data if i.get('order_required')])} products</li>
            <li>🏷️ Suggested markdowns for {len(critical)} critical items</li>
            <li>📈 Review {len(monitor)} monitor items this week</li>
        </ul>
        
        <p><small>Dishii AI - Automated Intelligence</small></p>
    </body>
    </html>
    """
    
    send_email_alert(f"Daily Report - {datetime.now().strftime('%Y-%m-%d')}", report_html)
    print("📧 Daily report sent")
    log_automation("daily_report", "success")

# ============================================
# MAIN EXECUTION
# ============================================

def run_full_automation():
    """Run all automation tasks in sequence"""
    print("=" * 50)
    print(f"🤖 DISHII AI AGENT RUNNING at {datetime.now()}")
    print("=" * 50)
    
    # Step 1: Update expiry dates
    update_all_inventory_expiry()
    
    # Step 2: Save daily snapshot for learning
    save_daily_snapshot()
    
    # Step 3: Detect critical items
    critical_items = detect_critical_items()
    
    # Step 4: Calculate learned trends
    calculate_learned_trends()
    
    # Step 5: Generate AI alerts if critical
    if critical_items:
        ai_message = generate_ai_alerts(critical_items)
        send_alerts(critical_items, ai_message)
    
    # Step 6: Send daily report
    generate_daily_report()
    
    print("=" * 50)
    print("✅ DISHII AI AGENT COMPLETE")
    print("=" * 50)

if __name__ == "__main__":
    run_full_automation()