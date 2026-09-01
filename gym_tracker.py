#!/usr/bin/env python3
"""
Bugema University Gym Membership & Expiration Tracker
A robust Python CLI application using SQLite to track member subscriptions,
calculate expiration dates, apply smart renewal business logic, and monitor statuses.
"""

import os
import sys
import sqlite3
import re
import contextlib
from datetime import datetime, date

# Database filename
DB_NAME = "gym.db"

# Color Codes for Terminal Output (cross-platform compatibility helper)
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

# Initialize console colors on Windows Command Prompt if needed
if sys.platform.startswith('win'):
    os.system('color')


class DateHelper:
    """Helper class for handling datetime calculations in pure Python."""
    
    @staticmethod
    def add_months(source_date: date, months: int) -> date:
        """
        Calculates a new date by adding the specified number of calendar months.
        Correctly handles month-end bounds (e.g., Feb 28th/29th, Jan 31st).
        """
        month = source_date.month - 1 + months
        year = source_date.year + month // 12
        month = month % 12 + 1
        
        # Calculate days in the target month (handles leap years for February)
        is_leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        days_in_months = [31, 29 if is_leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        
        day = min(source_date.day, days_in_months[month - 1])
        return date(year, month, day)

    @staticmethod
    def parse_date(date_str: str) -> date:
        """Parses a string in YYYY-MM-DD format into a datetime.date object."""
        return datetime.strptime(date_str, "%Y-%m-%d").date()

    @staticmethod
    def format_date(d: date) -> str:
        """Formats a datetime.date object as a YYYY-MM-DD string."""
        return d.strftime("%Y-%m-%d")


class DatabaseManager:
    """Encapsulates SQLite connection, schema definition, and querying with parameters."""
    
    def __init__(self, db_path: str = DB_NAME):
        self.db_path = db_path
        self._initialize_database()

    @contextlib.contextmanager
    def connection(self):
        """
        Context manager that yields a connection, handles transactions, 
        and guarantees the connection is closed to release file locks.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Access columns by name
        conn.execute("PRAGMA foreign_keys = ON")  # Enforce foreign key constraints
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize_database(self):
        """Creates table schemas if they do not exist."""
        with self.connection() as conn:
            # Plans table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS plans (
                    plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    duration_months INTEGER NOT NULL,
                    price REAL NOT NULL
                )
            """)
            
            # Members table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS members (
                    member_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    email TEXT,
                    plan_id INTEGER NOT NULL,
                    start_date TEXT NOT NULL,
                    expiration_date TEXT NOT NULL,
                    FOREIGN KEY (plan_id) REFERENCES plans (plan_id)
                )
            """)
            
            # Renewals table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS renewals (
                    renewal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    member_id INTEGER NOT NULL,
                    plan_id INTEGER NOT NULL,
                    renewal_date TEXT NOT NULL,
                    old_expiration_date TEXT,
                    new_expiration_date TEXT NOT NULL,
                    amount_paid REAL NOT NULL,
                    FOREIGN KEY (member_id) REFERENCES members (member_id) ON DELETE CASCADE,
                    FOREIGN KEY (plan_id) REFERENCES plans (plan_id)
                )
            """)

    def seed_data_if_empty(self):
        """Seeds default subscription plans and some dummy members in varying states."""
        with self.connection() as conn:
            # Check if plans table is empty
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM plans")
            if cursor.fetchone()[0] > 0:
                return  # Database is already seeded
            
            # Seed subscription plans
            plans = [
                ("Monthly Subscription", 1, 50000.0),
                ("Quarterly Subscription", 3, 130000.0),
                ("Semiannual Subscription", 6, 240000.0),
                ("Annual Subscription", 12, 450000.0)
            ]
            conn.executemany(
                "INSERT INTO plans (name, duration_months, price) VALUES (?, ?, ?)",
                plans
            )
            
            # Seed members in varying subscription states based on local test date: 2026-08-27
            # Note: Let's assume today is 2026-08-27
            members = [
                # Active members
                ("John Doe", "0771234567", "john.doe@email.com", 1, "2026-08-15", "2026-09-15"),
                ("Sarah Nabakooza", "0752345678", "sarah.n@email.com", 2, "2026-08-10", "2026-11-10"),
                # Expiring soon members (within 7 days of 2026-08-27)
                ("David Okello", "0783456789", "david.okello@email.com", 2, "2026-05-30", "2026-08-30"),  # Expires in 3 days
                ("Grace Amongin", "0704567890", "grace.a@email.com", 1, "2026-08-01", "2026-09-01"),       # Expires in 5 days
                # Expired members
                ("Moses Mukasa", "0715678901", "moses.mukasa@email.com", 1, "2026-07-20", "2026-08-20"),  # Expired 7 days ago
                ("Alice Nsubuga", "0776789012", "alice.n@email.com", 2, "2026-02-15", "2026-05-15")       # Expired months ago
            ]
            
            for name, phone, email, plan_id, start_date, exp_date in members:
                # Insert member
                cursor.execute("""
                    INSERT INTO members (full_name, phone, email, plan_id, start_date, expiration_date)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (name, phone, email, plan_id, start_date, exp_date))
                
                member_id = cursor.lastrowid
                
                # Fetch plan price to insert a renewal history record
                cursor.execute("SELECT price FROM plans WHERE plan_id = ?", (plan_id,))
                price = cursor.fetchone()[0]
                
                # Create initial renewal history record
                cursor.execute("""
                    INSERT INTO renewals (member_id, plan_id, renewal_date, old_expiration_date, new_expiration_date, amount_paid)
                    VALUES (?, ?, ?, NULL, ?, ?)
                """, (member_id, plan_id, start_date, exp_date, price))


class MembershipManager:
    """Handles the core domain logic: dynamic dates, smart renewals, and status classification."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db

    def get_plans(self):
        """Fetches all subscription plans."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM plans ORDER BY duration_months ASC")
            return cursor.fetchall()

    def get_plan_by_id(self, plan_id: int):
        """Fetches details of a specific plan by ID."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM plans WHERE plan_id = ?", (plan_id,))
            return cursor.fetchone()

    def register_member(self, full_name: str, phone: str, email: str, plan_id: int, start_date_str: str) -> dict:
        """
        Registers a new member, dynamically calculates their expiration date,
        saves to database, and records the initial subscription history.
        """
        # Validate plan
        plan = self.get_plan_by_id(plan_id)
        if not plan:
            raise ValueError(f"Subscription plan ID {plan_id} does not exist.")
        
        start_date = DateHelper.parse_date(start_date_str)
        expiration_date = DateHelper.add_months(start_date, plan['duration_months'])
        
        expiration_date_str = DateHelper.format_date(expiration_date)
        
        with self.db.connection() as conn:
            cursor = conn.cursor()
            # 1. Insert Member
            cursor.execute("""
                INSERT INTO members (full_name, phone, email, plan_id, start_date, expiration_date)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (full_name, phone, email, plan_id, start_date_str, expiration_date_str))
            
            member_id = cursor.lastrowid
            
            # 2. Record initial renewal history
            cursor.execute("""
                INSERT INTO renewals (member_id, plan_id, renewal_date, old_expiration_date, new_expiration_date, amount_paid)
                VALUES (?, ?, ?, NULL, ?, ?)
            """, (member_id, plan_id, start_date_str, expiration_date_str, plan['price']))
            
            return {
                "member_id": member_id,
                "full_name": full_name,
                "start_date": start_date_str,
                "expiration_date": expiration_date_str
            }

    def renew_membership(self, member_id: int, plan_id: int, renewal_date_str: str) -> dict:
        """
        Processes a subscription renewal implementing smart renewal business logic.
        - If today (renewal_date) <= current_expiration_date, extend from old expiration date.
        - If today (renewal_date) > current_expiration_date, extend from renewal date (today).
        """
        with self.db.connection() as conn:
            cursor = conn.cursor()
            
            # 1. Fetch current member details
            cursor.execute("SELECT * FROM members WHERE member_id = ?", (member_id,))
            member = cursor.fetchone()
            if not member:
                raise ValueError(f"Gym member ID {member_id} does not exist.")
            
            # 2. Fetch selected plan details
            cursor.execute("SELECT * FROM plans WHERE plan_id = ?", (plan_id,))
            plan = cursor.fetchone()
            if not plan:
                raise ValueError(f"Subscription plan ID {plan_id} does not exist.")
            
            renewal_date = DateHelper.parse_date(renewal_date_str)
            old_expiration_date = DateHelper.parse_date(member['expiration_date'])
            
            # Smart renewal logic:
            if renewal_date <= old_expiration_date:
                # Renewing BEFORE expiration -> Extend from existing expiration date
                new_start_date = old_expiration_date
                renew_type = "EXTENSION"
            else:
                # Renewing AFTER expiration -> Start from the date of renewal (today)
                new_start_date = renewal_date
                renew_type = "NEW_START"
                
            new_expiration_date = DateHelper.add_months(new_start_date, plan['duration_months'])
            
            new_start_date_str = DateHelper.format_date(new_start_date)
            new_expiration_date_str = DateHelper.format_date(new_expiration_date)
            old_expiration_date_str = DateHelper.format_date(old_expiration_date)
            
            # 3. Update Member Table
            cursor.execute("""
                UPDATE members
                SET plan_id = ?, start_date = ?, expiration_date = ?
                WHERE member_id = ?
            """, (plan_id, new_start_date_str, new_expiration_date_str, member_id))
            
            # 4. Insert Renewal History Record
            cursor.execute("""
                INSERT INTO renewals (member_id, plan_id, renewal_date, old_expiration_date, new_expiration_date, amount_paid)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (member_id, plan_id, renewal_date_str, old_expiration_date_str, new_expiration_date_str, plan['price']))
            
            return {
                "member_id": member_id,
                "full_name": member['full_name'],
                "old_expiration_date": old_expiration_date_str,
                "new_start_date": new_start_date_str,
                "new_expiration_date": new_expiration_date_str,
                "renew_type": renew_type,
                "price": plan['price']
            }

    def fetch_members_report(self, search_query: str = "", filter_status: str = "ALL", custom_threshold: int = 7, current_date_str: str = None) -> list:
        """
        Fetches member details, filters them based on search queries and status,
        and dynamically calculates status class and remaining days.
        """
        if current_date_str is None:
            today = date.today()
        else:
            today = DateHelper.parse_date(current_date_str)
            
        sql_query = """
            SELECT m.member_id, m.full_name, m.phone, m.email, m.start_date, m.expiration_date, p.name AS plan_name
            FROM members m
            JOIN plans p ON m.plan_id = p.plan_id
        """
        params = []
        
        # Add search filter
        if search_query:
            sql_query += " WHERE (m.full_name LIKE ? OR m.phone LIKE ? OR m.email LIKE ?)"
            like_pat = f"%{search_query}%"
            params.extend([like_pat, like_pat, like_pat])
            
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql_query, params)
            rows = cursor.fetchall()
            
        # Process and categorize members
        categorized_members = []
        for r in rows:
            exp_date = DateHelper.parse_date(r['expiration_date'])
            days_remaining = (exp_date - today).days
            
            # Status classification
            if days_remaining < 0:
                status = "EXPIRED"
            elif days_remaining <= custom_threshold:
                status = "EXPIRING SOON"
            else:
                status = "ACTIVE"
                
            member_dict = {
                "member_id": r['member_id'],
                "full_name": r['full_name'],
                "phone": r['phone'],
                "email": r['email'] if r['email'] else "N/A",
                "start_date": r['start_date'],
                "expiration_date": r['expiration_date'],
                "plan_name": r['plan_name'],
                "days_remaining": days_remaining,
                "status": status
            }
            
            # Filter output based on selection
            if filter_status == "ALL" or member_dict["status"] == filter_status:
                categorized_members.append(member_dict)
                
        # Sort by status (Expired first, then Expiring Soon, then Active) and expiration date
        status_priority = {"EXPIRED": 0, "EXPIRING SOON": 1, "ACTIVE": 2}
        categorized_members.sort(key=lambda x: (status_priority[x["status"]], x["days_remaining"]))
        
        return categorized_members

    def get_summary_statistics(self, custom_threshold: int = 7, current_date_str: str = None) -> dict:
        """Computes counts of members in each status category for the dashboard."""
        all_members = self.fetch_members_report(filter_status="ALL", custom_threshold=custom_threshold, current_date_str=current_date_str)
        stats = {
            "total": len(all_members),
            "active": sum(1 for m in all_members if m["status"] == "ACTIVE"),
            "expiring_soon": sum(1 for m in all_members if m["status"] == "EXPIRING SOON"),
            "expired": sum(1 for m in all_members if m["status"] == "EXPIRED")
        }
        return stats

    def get_renewal_history(self, member_id: int = None) -> list:
        """Fetches historical renewal logs for all members or a specific member."""
        query = """
            SELECT r.renewal_id, m.full_name, p.name AS plan_name, r.renewal_date, r.old_expiration_date, r.new_expiration_date, r.amount_paid
            FROM renewals r
            JOIN members m ON r.member_id = m.member_id
            JOIN plans p ON r.plan_id = p.plan_id
        """
        params = []
        if member_id is not None:
            query += " WHERE r.member_id = ?"
            params.append(member_id)
            
        query += " ORDER BY r.renewal_id DESC"
        
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()


class GymCLI:
    """Manages the console interactive flow, text forms, menu navigation, and validations."""
    
    def __init__(self, manager: MembershipManager):
        self.manager = manager
        # Customizable threshold for expiring soon (default: 7 days)
        self.exp_threshold = 7
        # Configurable virtual system date for testing/evaluation
        self.system_date_str = "2026-08-27"  # Hardcoded system date matching current local setting

    def print_header(self, title: str):
        """Prints a decorated section header."""
        border = "═" * 70
        print(f"\n{Colors.BLUE}{Colors.BOLD}{border}")
        print(f"  {title.upper()}")
        print(f"{border}{Colors.END}")

    def show_dashboard(self):
        """Renders summary cards and any critical expiration alerts."""
        stats = self.manager.get_summary_statistics(
            custom_threshold=self.exp_threshold, 
            current_date_str=self.system_date_str
        )
        
        print(f"\n{Colors.BOLD}SYSTEM DATE: {self.system_date_str} (Threshold: {self.exp_threshold} days){Colors.END}")
        
        # Draw stats boxes
        print("┌─────────────────┬─────────────────┬─────────────────┬─────────────────┐")
        print(f"│  TOTAL MEMBERS  │     ACTIVE      │  EXPIRING SOON  │     EXPIRED     │")
        print("├─────────────────┼─────────────────┼─────────────────┼─────────────────┤")
        print(f"│ {str(stats['total']).center(15)} │ {Colors.GREEN}{str(stats['active']).center(15)}{Colors.END} │ {Colors.YELLOW}{str(stats['expiring_soon']).center(15)}{Colors.END} │ {Colors.RED}{str(stats['expired']).center(15)}{Colors.END} │")
        print("└─────────────────┴─────────────────┴─────────────────┴─────────────────┘")
        
        # Fetch members expiring soon or expired to show immediate warning alerts
        urgent_members = self.manager.fetch_members_report(
            filter_status="EXPIRING SOON", 
            custom_threshold=self.exp_threshold, 
            current_date_str=self.system_date_str
        )
        expired_members = self.manager.fetch_members_report(
            filter_status="EXPIRED", 
            custom_threshold=self.exp_threshold, 
            current_date_str=self.system_date_str
        )
        
        if urgent_members or expired_members:
            print(f"\n{Colors.BOLD}{Colors.RED}⚠️ EXPIRES & EXPIRATION ALERTS:{Colors.END}")
            # Show expired alerts
            for m in expired_members[:5]:
                print(f"  {Colors.RED}[EXPIRED]{Colors.END} {m['full_name']} ({m['phone']}) - Expired {abs(m['days_remaining'])} day(s) ago on {m['expiration_date']}")
            if len(expired_members) > 5:
                print(f"  ... and {len(expired_members) - 5} more expired member(s).")
                
            # Show expiring soon alerts
            for m in urgent_members[:5]:
                print(f"  {Colors.YELLOW}[EXPIRING SOON]{Colors.END} {m['full_name']} ({m['phone']}) - Expires in {m['days_remaining']} day(s) on {m['expiration_date']}")
            if len(urgent_members) > 5:
                print(f"  ... and {len(urgent_members) - 5} more expiring soon member(s).")

    def run(self):
        """Core application lifecycle loop."""
        while True:
            self.print_header("Bugema University Gym Tracker")
            self.show_dashboard()
            
            print(f"\n{Colors.BOLD}Main Menu:{Colors.END}")
            print(f" 1. {Colors.BLUE}Register New Member{Colors.END}")
            print(f" 2. {Colors.BLUE}Renew Membership{Colors.END}")
            print(f" 3. {Colors.BLUE}View Member Records / Directory{Colors.END}")
            print(f" 4. {Colors.BLUE}View Renewal Logs & History{Colors.END}")
            print(f" 5. {Colors.BLUE}System Configuration & Settings{Colors.END}")
            print(f" 0. {Colors.BOLD}{Colors.RED}Exit Tracker{Colors.END}")
            
            choice = input(f"\nChoose an option (0-5): ").strip()
            
            try:
                if choice == '1':
                    self.ui_register_member()
                elif choice == '2':
                    self.ui_renew_membership()
                elif choice == '3':
                    self.ui_list_members()
                elif choice == '4':
                    self.ui_view_renewal_logs()
                elif choice == '5':
                    self.ui_system_settings()
                elif choice == '0':
                    print(f"\n{Colors.GREEN}Thank you for using Bugema University Gym Tracker. Goodbye!{Colors.END}")
                    break
                else:
                    print(f"\n{Colors.RED}Error: Invalid menu option. Please select 0 to 5.{Colors.END}")
            except Exception as e:
                print(f"\n{Colors.RED}Runtime Exception Encountered: {e}{Colors.END}")
                
            input(f"\nPress Enter to return to Main Menu...")

    # --- UI MODULES WITH INPUT VALIDATIONS ---
    
    def ui_register_member(self):
        self.print_header("Register New Member")
        
        # Name Validation
        while True:
            name = input("Enter Member Full Name: ").strip()
            if not name:
                print(f"{Colors.RED}Error: Full name is required.{Colors.END}")
                continue
            if not re.match(r"^[a-zA-Z\s'\-]{2,50}$", name):
                print(f"{Colors.RED}Error: Name must contain only alphabetical characters, spaces, hyphens, or apostrophes (2-50 chars).{Colors.END}")
                continue
            break
            
        # Phone Validation
        while True:
            phone = input("Enter Contact Number: ").strip()
            if not phone:
                print(f"{Colors.RED}Error: Contact number is required.{Colors.END}")
                continue
            if not re.match(r"^\+?[0-9\s\-()]{7,15}$", phone):
                print(f"{Colors.RED}Error: Invalid phone format. Example: 0771234567 or +256771234567.{Colors.END}")
                continue
            break
            
        # Email Validation (Optional)
        while True:
            email = input("Enter Email Address (Optional - Press Enter to skip): ").strip()
            if not email:
                email = None
                break
            if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email):
                print(f"{Colors.RED}Error: Invalid email address format. Example: name@domain.com.{Colors.END}")
                continue
            break
            
        # Select Plan
        plans = self.manager.get_plans()
        print(f"\nAvailable Subscription Plans:")
        for idx, plan in enumerate(plans, 1):
            print(f" {idx}. {plan['name']} - {plan['duration_months']} Month(s) @ {plan['price']:,.2f} UGX")
            
        while True:
            try:
                plan_choice = input(f"Select Plan Option (1-{len(plans)}): ").strip()
                p_idx = int(plan_choice) - 1
                if 0 <= p_idx < len(plans):
                    selected_plan = plans[p_idx]
                    break
                else:
                    print(f"{Colors.RED}Error: Option out of range.{Colors.END}")
            except ValueError:
                print(f"{Colors.RED}Error: Please enter a valid number.{Colors.END}")

        # Start Date Selection
        while True:
            start_choice = input(f"Enter Start Date (YYYY-MM-DD) [Default: {self.system_date_str}]: ").strip()
            if not start_choice:
                start_date_str = self.system_date_str
                break
            try:
                # Verify date formatting and validity
                DateHelper.parse_date(start_choice)
                start_date_str = start_choice
                break
            except ValueError:
                print(f"{Colors.RED}Error: Invalid date format or non-existent date. Must be YYYY-MM-DD.{Colors.END}")

        # Execute Registration
        result = self.manager.register_member(
            full_name=name,
            phone=phone,
            email=email,
            plan_id=selected_plan['plan_id'],
            start_date_str=start_date_str
        )
        
        print(f"\n{Colors.GREEN}{Colors.BOLD}✔ Registration Successful!{Colors.END}")
        print(f"  Member ID: {result['member_id']}")
        print(f"  Name: {result['full_name']}")
        print(f"  Subscription Plan: {selected_plan['name']}")
        print(f"  Duration: {selected_plan['duration_months']} Month(s)")
        print(f"  Start Date: {result['start_date']}")
        print(f"  Calculated Expiration Date: {Colors.BOLD}{result['expiration_date']}{Colors.END}")

    def ui_renew_membership(self):
        self.print_header("Renew Gym Membership")
        
        # Search for member to renew
        search_query = input("Enter Member Name or Phone to search: ").strip()
        matching_members = self.manager.fetch_members_report(
            search_query=search_query, 
            filter_status="ALL", 
            current_date_str=self.system_date_str
        )
        
        if not matching_members:
            print(f"{Colors.RED}No members found matching that search.{Colors.END}")
            return
            
        print(f"\nSelect a Member to Renew:")
        for idx, m in enumerate(matching_members, 1):
            status_colored = self._get_status_colored(m['status'])
            print(f" {idx}. {m['full_name']} (Phone: {m['phone']}, Cur Exp: {m['expiration_date']}) [{status_colored}]")
            
        while True:
            try:
                m_choice = input(f"Select Member (1-{len(matching_members)}): ").strip()
                m_idx = int(m_choice) - 1
                if 0 <= m_idx < len(matching_members):
                    selected_member = matching_members[m_idx]
                    break
                else:
                    print(f"{Colors.RED}Error: Option out of range.{Colors.END}")
            except ValueError:
                print(f"{Colors.RED}Error: Please enter a valid number.{Colors.END}")

        # Choose renewal plan
        plans = self.manager.get_plans()
        print(f"\nSelect Subscription Renewal Plan:")
        for idx, plan in enumerate(plans, 1):
            print(f" {idx}. {plan['name']} - {plan['duration_months']} Month(s) @ {plan['price']:,.2f} UGX")
            
        while True:
            try:
                plan_choice = input(f"Select Plan Option (1-{len(plans)}): ").strip()
                p_idx = int(plan_choice) - 1
                if 0 <= p_idx < len(plans):
                    selected_plan = plans[p_idx]
                    break
                else:
                    print(f"{Colors.RED}Error: Option out of range.{Colors.END}")
            except ValueError:
                print(f"{Colors.RED}Error: Please enter a valid number.{Colors.END}")

        # Renewal Date Selection
        while True:
            renewal_choice = input(f"Enter Date of Renewal Transaction (YYYY-MM-DD) [Default Today: {self.system_date_str}]: ").strip()
            if not renewal_choice:
                renewal_date_str = self.system_date_str
                break
            try:
                DateHelper.parse_date(renewal_choice)
                renewal_date_str = renewal_choice
                break
            except ValueError:
                print(f"{Colors.RED}Error: Invalid date format. Must be YYYY-MM-DD.{Colors.END}")

        # Execute Smart Renewal logic
        result = self.manager.renew_membership(
            member_id=selected_member['member_id'],
            plan_id=selected_plan['plan_id'],
            renewal_date_str=renewal_date_str
        )
        
        print(f"\n{Colors.GREEN}{Colors.BOLD}✔ Renewal Transaction Processed!{Colors.END}")
        print(f"  Member: {result['full_name']} (ID: {result['member_id']})")
        print(f"  Chosen Plan: {selected_plan['name']}")
        print(f"  Old Expiration Date: {result['old_expiration_date']}")
        print(f"  Transaction Date: {renewal_date_str}")
        
        if result['renew_type'] == "EXTENSION":
            print(f"  {Colors.GREEN}Smart Logic Applied: Active account extended from old expiration date.{Colors.END}")
        else:
            print(f"  {Colors.YELLOW}Smart Logic Applied: Lapsed/expired account renewed from date of transaction.{Colors.END}")
            
        print(f"  Subscription Start Date: {result['new_start_date']}")
        print(f"  New Expiration Date: {Colors.BOLD}{Colors.GREEN}{result['new_expiration_date']}{Colors.END}")
        print(f"  Amount Due: {result['price']:,.2f} UGX")

    def ui_list_members(self):
        self.print_header("Gym Member Directory")
        
        print("Filter Options:")
        print(" 1. All Members")
        print(" 2. Active Members Only")
        print(" 3. Expiring Soon Members Only")
        print(" 4. Expired Members Only")
        
        filter_map = {"1": "ALL", "2": "ACTIVE", "3": "EXPIRING SOON", "4": "EXPIRED"}
        while True:
            f_choice = input("Select filter option (1-4) [Default: 1]: ").strip()
            if not f_choice:
                status_filter = "ALL"
                break
            if f_choice in filter_map:
                status_filter = filter_map[f_choice]
                break
            print(f"{Colors.RED}Error: Select 1, 2, 3, or 4.{Colors.END}")
            
        search_query = input("Search by Name / Phone / Email (Press Enter for all): ").strip()
        
        members = self.manager.fetch_members_report(
            search_query=search_query,
            filter_status=status_filter,
            custom_threshold=self.exp_threshold,
            current_date_str=self.system_date_str
        )
        
        if not members:
            print(f"\n{Colors.YELLOW}No member records found matching the criteria.{Colors.END}")
            return
            
        # Display Table
        self._print_members_table(members)

    def ui_view_renewal_logs(self):
        self.print_header("Subscription Renewal Audit Logs")
        
        search_choice = input("Enter Member Name to filter logs (Press Enter for all logs): ").strip()
        
        member_id = None
        if search_choice:
            # Look up member
            matching_members = self.manager.fetch_members_report(
                search_query=search_choice, 
                filter_status="ALL", 
                current_date_str=self.system_date_str
            )
            if not matching_members:
                print(f"{Colors.RED}No members found matching '{search_choice}'.{Colors.END}")
                return
            elif len(matching_members) == 1:
                member_id = matching_members[0]['member_id']
                print(f"Showing logs for: {matching_members[0]['full_name']}")
            else:
                print("\nMultiple members found. Select one:")
                for idx, m in enumerate(matching_members, 1):
                    print(f" {idx}. {m['full_name']} (Phone: {m['phone']})")
                while True:
                    try:
                        m_choice = input(f"Select Member (1-{len(matching_members)}): ").strip()
                        m_idx = int(m_choice) - 1
                        if 0 <= m_idx < len(matching_members):
                            member_id = matching_members[m_idx]['member_id']
                            break
                        else:
                            print(f"{Colors.RED}Error: Out of range.{Colors.END}")
                    except ValueError:
                        print(f"{Colors.RED}Error: Valid number required.{Colors.END}")

        logs = self.manager.get_renewal_history(member_id)
        
        if not logs:
            print(f"\n{Colors.YELLOW}No renewal audit logs found.{Colors.END}")
            return
            
        # Draw logs table
        print(f"\n┌─────┬──────────────────────┬──────────────────────┬────────────┬────────────┬────────────┬──────────────┐")
        print(f"│ ID  │ Member Name          │ Plan Duration        │ Date Paid  │ Old Expiry │ New Expiry │ Amount Paid  │")
        print(f"├─────┼──────────────────────┼──────────────────────┼────────────┼────────────┼────────────┼──────────────┤")
        for log in logs:
            old_exp = log['old_expiration_date'] if log['old_expiration_date'] else "N/A (New)"
            print(f"│ {str(log['renewal_id']).ljust(3)} │ "
                  f"{log['full_name'][:20].ljust(20)} │ "
                  f"{log['plan_name'][:20].ljust(20)} │ "
                  f"{log['renewal_date'].ljust(10)} │ "
                  f"{old_exp.ljust(10)} │ "
                  f"{log['new_expiration_date'].ljust(10)} │ "
                  f"{f'{log[6]:,.0f} UGX'.rjust(12)} │")
        print(f"└─────┴──────────────────────┴──────────────────────┴────────────┴────────────┴────────────┴──────────────┘")

    def ui_system_settings(self):
        self.print_header("System Settings")
        print(f"Current System Config:")
        print(f" 1. Expiration Notification Threshold: {self.exp_threshold} days")
        print(f" 2. Active Virtual Date: {self.system_date_str}")
        print(f" 3. Back to Main Menu")
        
        choice = input("\nSelect setting to modify (1-3): ").strip()
        if choice == '1':
            while True:
                threshold_choice = input("Enter new notification threshold (days, 1-30): ").strip()
                try:
                    t = int(threshold_choice)
                    if 1 <= t <= 30:
                        self.exp_threshold = t
                        print(f"{Colors.GREEN}Threshold successfully updated to {t} days.{Colors.END}")
                        break
                    else:
                        print(f"{Colors.RED}Error: Threshold must be between 1 and 30 days.{Colors.END}")
                except ValueError:
                    print(f"{Colors.RED}Error: Invalid integer input.{Colors.END}")
        elif choice == '2':
            while True:
                date_choice = input("Enter virtual system date (YYYY-MM-DD): ").strip()
                try:
                    DateHelper.parse_date(date_choice)
                    self.system_date_str = date_choice
                    print(f"{Colors.GREEN}Virtual system date successfully updated to {date_choice}.{Colors.END}")
                    break
                except ValueError:
                    print(f"{Colors.RED}Error: Invalid date format. Must be YYYY-MM-DD.{Colors.END}")
        elif choice == '3':
            return
        else:
            print(f"{Colors.RED}Invalid option selected.{Colors.END}")

    def _get_status_colored(self, status: str) -> str:
        """Returns colored status labels."""
        if status == "ACTIVE":
            return f"{Colors.GREEN}{status}{Colors.END}"
        elif status == "EXPIRING SOON":
            return f"{Colors.YELLOW}{status}{Colors.END}"
        elif status == "EXPIRED":
            return f"{Colors.RED}{status}{Colors.END}"
        return status

    def _print_members_table(self, members: list):
        """Draws a beautiful unicode formatted table of members."""
        print(f"\n┌────┬──────────────────────┬────────────────┬────────────────────────┬────────────┬────────────┬───────────┬───────────────┐")
        print(f"│ ID │ Full Name            │ Phone          │ Subscription Plan      │ Start Date │ Exp Date   │ Days Left │ Status        │")
        print(f"├────┼──────────────────────┼────────────────┼────────────────────────┼────────────┼────────────┼───────────┼───────────────┤")
        for m in members:
            days_str = str(m['days_remaining'])
            status_colored = self._get_status_colored(m['status'])
            
            # Pad status representation correctly for colored ANSI escaping
            status_padding = 13 - len(m['status'])
            status_display = status_colored + (" " * status_padding)
            
            # Handle days left formatting
            if m['days_remaining'] < 0:
                days_disp = f"{Colors.RED}{days_str.rjust(9)}{Colors.END}"
            elif m['days_remaining'] <= self.exp_threshold:
                days_disp = f"{Colors.YELLOW}{days_str.rjust(9)}{Colors.END}"
            else:
                days_disp = f"{Colors.GREEN}{days_str.rjust(9)}{Colors.END}"
                
            print(f"│ {str(m['member_id']).ljust(2)} │ "
                  f"{m['full_name'][:20].ljust(20)} │ "
                  f"{m['phone'].ljust(14)} │ "
                  f"{m['plan_name'][:22].ljust(22)} │ "
                  f"{m['start_date']} │ "
                  f"{m['expiration_date']} │ "
                  f"{days_disp} │ "
                  f"{status_display} │")
        print(f"└────┴──────────────────────┴────────────────┴────────────────────────┴────────────┴────────────┴───────────┴───────────────┘")


def main():
    # Setup database
    db_mgr = DatabaseManager()
    db_mgr.seed_data_if_empty()
    
    # Setup business logic manager
    membership_mgr = MembershipManager(db_mgr)
    
    # Initialize CLI interface and run
    cli = GymCLI(membership_mgr)
    
    # Check for CLI args (e.g. testing)
    if len(sys.argv) > 1 and sys.argv[1] == "--seed-only":
        print("Database initialized and pre-populated with test data.")
        sys.exit(0)
        
    cli.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{Colors.RED}Process interrupted by user. Exiting Gym Tracker...{Colors.END}")
        sys.exit(0)
