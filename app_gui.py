#!/usr/bin/env python3
"""
Bugema University Gym — Desktop Reception Application
A modern desktop GUI for gym receptionists to manage member registrations,
monitor expiration dates, process renewals, and track live attendance synced with the website.

Can be launched directly by double-clicking the Desktop shortcut or app_gui.py (via pythonw.exe).
"""

import os
import sys
import threading
from datetime import datetime, date, timedelta
import tkinter as tk
from tkinter import ttk, messagebox

# Ensure current directory is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from gym_tracker import DatabaseManager, MembershipManager, DateHelper, start_background_api_bridge
import sqlite3

APP_TITLE = "Bugema University Gym — Reception Tracker"
DB_PATH = os.path.join(BASE_DIR, "gym.db")


class GymDesktopApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1100x720")
        self.minsize(950, 600)
        
        # Set icon if available, or configure styling
        self.configure(bg="#F4F6F9")

        # Initialize database and managers
        self.db_mgr = DatabaseManager(DB_PATH)
        self.db_mgr.seed_data_if_empty()
        self.db_mgr.ensure_website_plans()
        self.manager = MembershipManager(self.db_mgr)

        # Start API bridge in background so website auto-syncs
        start_background_api_bridge()

        # Custom Styling
        self.setup_styles()

        # Build UI layout
        self.create_header()
        self.create_dashboard_banner()
        self.create_tabs()
        self.create_status_bar()

        # Load initial data
        self.refresh_all_data()

        # Start background polling timer (auto-refresh every 5 seconds to catch website bookings)
        self.after(5000, self.auto_refresh_loop)

    def setup_styles(self):
        self.style = ttk.Style(self)
        # Use clam or native theme
        available_themes = self.style.theme_names()
        if "vista" in available_themes:
            self.style.theme_use("vista")
        elif "clam" in available_themes:
            self.style.theme_use("clam")

        # Fonts & colors
        self.style.configure(".", font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"), foreground="#002147", background="#FFFFFF")
        self.style.configure("SubHeader.TLabel", font=("Segoe UI", 10), foreground="#666666", background="#FFFFFF")
        
        # Tabs
        self.style.configure("TNotebook", background="#F4F6F9", borderwidth=0)
        self.style.configure("TNotebook.Tab", font=("Segoe UI", 10, "bold"), padding=[16, 8])
        self.style.map("TNotebook.Tab",
                       background=[("selected", "#002147"), ("!selected", "#E2E8F0")],
                       foreground=[("selected", "#FFFFFF"), ("!selected", "#333333")])

        # Treeview styling
        self.style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), foreground="#002147", background="#EAECEE", relief="flat")
        self.style.configure("Treeview", font=("Segoe UI", 10), rowheight=28)
        self.style.map("Treeview", background=[("selected", "#002147")], foreground=[("selected", "#FFFFFF")])

        # Primary Buttons
        self.style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), background="#002147", foreground="#FFFFFF")
        self.style.configure("Success.TButton", font=("Segoe UI", 10, "bold"), background="#27AE60", foreground="#FFFFFF")
        self.style.configure("Action.TButton", font=("Segoe UI", 10))

    def create_header(self):
        header_frame = tk.Frame(self, bg="#FFFFFF", height=70, relief="solid", bd=1)
        header_frame.pack(side="top", fill="x")

        # Inner container
        inner = tk.Frame(header_frame, bg="#FFFFFF", padx=20, pady=12)
        inner.pack(fill="both")

        # Title and Tagline
        title_box = tk.Frame(inner, bg="#FFFFFF")
        title_box.pack(side="left")

        title_lbl = tk.Label(title_box, text="BUGEMA UNIVERSITY GYM", font=("Segoe UI", 16, "bold"), fg="#002147", bg="#FFFFFF")
        title_lbl.pack(anchor="w")

        sub_lbl = tk.Label(title_box, text="Reception Front Desk & Membership Tracker", font=("Segoe UI", 9), fg="#7F8C8D", bg="#FFFFFF")
        sub_lbl.pack(anchor="w")

        # Right control panel (Sync status & refresh button)
        right_box = tk.Frame(inner, bg="#FFFFFF")
        right_box.pack(side="right")

        self.btn_refresh = tk.Button(right_box, text="↻ Refresh Data", font=("Segoe UI", 9, "bold"),
                                     bg="#002147", fg="#FFFFFF", activebackground="#0A3A6B", activeforeground="#FFFFFF",
                                     relief="flat", padx=12, pady=5, cursor="hand2", command=self.refresh_all_data)
        self.btn_refresh.pack(side="right", padx=6)

        sync_lbl = tk.Label(right_box, text="● Web Bridge: Active (Port 5050)", font=("Segoe UI", 9, "bold"), fg="#27AE60", bg="#FFFFFF")
        sync_lbl.pack(side="right", padx=12)

    def create_dashboard_banner(self):
        dash_frame = tk.Frame(self, bg="#F4F6F9", padx=16, pady=10)
        dash_frame.pack(side="top", fill="x")

        # Stat cards grid (including Pending Online Payments)
        self.card_total = self._make_stat_card(dash_frame, "ACTIVE MEMBERS", "0", "#2980B9")
        self.card_active = self._make_stat_card(dash_frame, "ACTIVE PASSES", "0", "#27AE60")
        self.card_expiring = self._make_stat_card(dash_frame, "EXPIRING SOON", "0", "#E67E22")
        self.card_expired = self._make_stat_card(dash_frame, "EXPIRED PASSES", "0", "#C0392B")
        self.card_pending = self._make_stat_card(dash_frame, "PENDING PAYMENTS", "0", "#D35400")

        self.card_total.pack(side="left", expand=True, fill="both", padx=4)
        self.card_active.pack(side="left", expand=True, fill="both", padx=4)
        self.card_expiring.pack(side="left", expand=True, fill="both", padx=4)
        self.card_expired.pack(side="left", expand=True, fill="both", padx=4)
        self.card_pending.pack(side="left", expand=True, fill="both", padx=4)

    def _make_stat_card(self, parent, title, initial_value, border_color):
        card = tk.Frame(parent, bg="#FFFFFF", relief="solid", bd=1, padx=14, pady=8)
        # Top color accent stripe
        stripe = tk.Frame(card, bg=border_color, height=4)
        stripe.pack(side="top", fill="x")

        t_lbl = tk.Label(card, text=title, font=("Segoe UI", 8, "bold"), fg="#7F8C8D", bg="#FFFFFF", pady=2)
        t_lbl.pack(anchor="w")

        val_lbl = tk.Label(card, text=initial_value, font=("Segoe UI", 18, "bold"), fg="#002147", bg="#FFFFFF")
        val_lbl.pack(anchor="w")

        card.val_lbl = val_lbl
        return card

    def create_tabs(self):
        container = tk.Frame(self, bg="#F4F6F9", padx=16, pady=4)
        container.pack(side="top", fill="both", expand=True)

        self.notebook = ttk.Notebook(container)
        self.notebook.pack(fill="both", expand=True)

        # Tab 1: Pending Approvals (Online Website Subscriptions)
        self.tab_pending = tk.Frame(self.notebook, bg="#FFFFFF", padx=16, pady=16)
        self.notebook.add(self.tab_pending, text="   ⏳ Pending Approvals (0)   ")
        self._build_pending_tab()

        # Tab 2: Member Directory
        self.tab_directory = tk.Frame(self.notebook, bg="#FFFFFF", padx=16, pady=16)
        self.notebook.add(self.tab_directory, text="   📋 Member Directory   ")
        self._build_directory_tab()

        # Tab 3: Register New Member
        self.tab_register = tk.Frame(self.notebook, bg="#FFFFFF", padx=24, pady=20)
        self.notebook.add(self.tab_register, text="   ➕ Register New Member   ")
        self._build_register_tab()

        # Tab 4: Renew Membership
        self.tab_renew = tk.Frame(self.notebook, bg="#FFFFFF", padx=24, pady=20)
        self.notebook.add(self.tab_renew, text="   🔄 Renew Subscription   ")
        self._build_renew_tab()

        # Tab 5: Daily Attendance
        self.tab_attendance = tk.Frame(self.notebook, bg="#FFFFFF", padx=16, pady=16)
        self.notebook.add(self.tab_attendance, text="   🏋️ Daily Attendance   ")
        self._build_attendance_tab()

        # Tab 6: Audit & Renewal Ledger
        self.tab_ledger = tk.Frame(self.notebook, bg="#FFFFFF", padx=16, pady=16)
        self.notebook.add(self.tab_ledger, text="   💰 Renewal Ledger   ")
        self._build_ledger_tab()

    # ─── TAB 1: PENDING APPROVALS ──────────────────────────────────────────
    def _build_pending_tab(self):
        top_frame = tk.Frame(self.tab_pending, bg="#FFFFFF")
        top_frame.pack(side="top", fill="x", pady=(0, 8))

        tk.Label(top_frame, text="Online Bookings Awaiting Counter Payment", font=("Segoe UI", 13, "bold"), fg="#002147", bg="#FFFFFF").pack(anchor="w")
        tk.Label(top_frame, text="When someone registers online, they appear here. Confirm their cash or mobile money payment to officially activate their membership.",
                 font=("Segoe UI", 9), fg="#7F8C8D", bg="#FFFFFF").pack(anchor="w")

        tree_frame = tk.Frame(self.tab_pending, bg="#FFFFFF")
        tree_frame.pack(side="top", fill="both", expand=True, pady=6)

        cols = ("ref", "name", "phone", "plan", "amount", "start_date", "created_at")
        self.tree_pending = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        self.tree_pending.heading("ref", text="Booking Ref")
        self.tree_pending.heading("name", text="Member Full Name")
        self.tree_pending.heading("phone", text="Phone Number")
        self.tree_pending.heading("plan", text="Requested Plan")
        self.tree_pending.heading("amount", text="Amount Due")
        self.tree_pending.heading("start_date", text="Preferred Start")
        self.tree_pending.heading("created_at", text="Booking Date")

        self.tree_pending.column("ref", width=110, anchor="center")
        self.tree_pending.column("name", width=190, anchor="w")
        self.tree_pending.column("phone", width=130, anchor="center")
        self.tree_pending.column("plan", width=180, anchor="w")
        self.tree_pending.column("amount", width=120, anchor="e")
        self.tree_pending.column("start_date", width=120, anchor="center")
        self.tree_pending.column("created_at", width=140, anchor="center")

        v_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree_pending.yview)
        self.tree_pending.configure(yscrollcommand=v_scroll.set)
        v_scroll.pack(side="right", fill="y")
        self.tree_pending.pack(side="left", fill="both", expand=True)

        # Action Buttons
        btn_frame = tk.Frame(self.tab_pending, bg="#FFFFFF", pady=10)
        btn_frame.pack(side="bottom", fill="x")

        self.btn_approve_pending = tk.Button(btn_frame, text="✓ Confirm Payment & Activate Member", font=("Segoe UI", 10, "bold"),
                                             bg="#27AE60", fg="#FFFFFF", activebackground="#219653", activeforeground="#FFFFFF",
                                             relief="flat", padx=16, pady=7, cursor="hand2", command=self.approve_selected_pending)
        self.btn_approve_pending.pack(side="left", padx=(0, 10))

        self.btn_reject_pending = tk.Button(btn_frame, text="✕ Reject / Cancel Booking", font=("Segoe UI", 10),
                                            bg="#E74C3C", fg="#FFFFFF", activebackground="#C0392B", activeforeground="#FFFFFF",
                                            relief="flat", padx=16, pady=7, cursor="hand2", command=self.reject_selected_pending)
        self.btn_reject_pending.pack(side="left", padx=10)

    # ─── TAB 1: DIRECTORY ──────────────────────────────────────────────────
    def _build_directory_tab(self):
        # Controls Row (Search + Filter)
        ctrl_frame = tk.Frame(self.tab_directory, bg="#FFFFFF")
        ctrl_frame.pack(side="top", fill="x", pady=(0, 12))

        tk.Label(ctrl_frame, text="Search Member:", font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#002147").pack(side="left", padx=(0, 6))
        self.search_var = tk.StringVar()
        self.search_var.trace("w", lambda *args: self.filter_directory())
        search_entry = ttk.Entry(ctrl_frame, textvariable=self.search_var, width=28)
        search_entry.pack(side="left", padx=4)

        tk.Label(ctrl_frame, text="Status Filter:", font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#002147").pack(side="left", padx=(18, 6))
        self.status_filter_var = tk.StringVar(value="ALL")
        status_combo = ttk.Combobox(ctrl_frame, textvariable=self.status_filter_var, state="readonly", width=16,
                                    values=["ALL", "ACTIVE", "EXPIRING SOON", "EXPIRED"])
        status_combo.pack(side="left", padx=4)
        status_combo.bind("<<ComboboxSelected>>", lambda e: self.filter_directory())

        # Treeview Table
        tree_frame = tk.Frame(self.tab_directory, bg="#FFFFFF")
        tree_frame.pack(side="top", fill="both", expand=True)

        columns = ("id", "name", "phone", "plan", "start_date", "expiration_date", "days", "status")
        self.tree_members = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")

        self.tree_members.heading("id", text="Member ID")
        self.tree_members.heading("name", text="Full Name")
        self.tree_members.heading("phone", text="Phone Number")
        self.tree_members.heading("plan", text="Subscription Plan")
        self.tree_members.heading("start_date", text="Start Date")
        self.tree_members.heading("expiration_date", text="Expiring Date")
        self.tree_members.heading("days", text="Days Left")
        self.tree_members.heading("status", text="Current Status")

        self.tree_members.column("id", width=95, anchor="center")
        self.tree_members.column("name", width=190, anchor="w")
        self.tree_members.column("phone", width=130, anchor="center")
        self.tree_members.column("plan", width=180, anchor="w")
        self.tree_members.column("start_date", width=105, anchor="center")
        self.tree_members.column("expiration_date", width=105, anchor="center")
        self.tree_members.column("days", width=90, anchor="center")
        self.tree_members.column("status", width=120, anchor="center")

        # Scrollbars
        v_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree_members.yview)
        self.tree_members.configure(yscrollcommand=v_scroll.set)
        v_scroll.pack(side="right", fill="y")
        self.tree_members.pack(side="left", fill="both", expand=True)

        # Tag coloring
        self.tree_members.tag_configure("ACTIVE", foreground="#27AE60")
        self.tree_members.tag_configure("EXPIRING SOON", foreground="#D35400", background="#FEF9E7")
        self.tree_members.tag_configure("EXPIRED", foreground="#C0392B", background="#FDEDEC")

    # ─── TAB 2: REGISTER NEW MEMBER ───────────────────────────────────────
    def _build_register_tab(self):
        title = tk.Label(self.tab_register, text="In-Person Reception Desk Registration", font=("Segoe UI", 14, "bold"), fg="#002147", bg="#FFFFFF")
        title.pack(anchor="w", pady=(0, 4))
        sub = tk.Label(self.tab_register, text="Enter the member's details below to create an active subscription pass in gym.db.", font=("Segoe UI", 9), fg="#7F8C8D", bg="#FFFFFF")
        sub.pack(anchor="w", pady=(0, 18))

        form_box = tk.Frame(self.tab_register, bg="#F8F9FA", relief="solid", bd=1, padx=24, pady=20)
        form_box.pack(anchor="w", fill="x", padx=10)

        # Full Name
        tk.Label(form_box, text="Full Name *", font=("Segoe UI", 10, "bold"), bg="#F8F9FA", fg="#002147").grid(row=0, column=0, sticky="w", pady=6)
        self.reg_name = ttk.Entry(form_box, width=42)
        self.reg_name.grid(row=0, column=1, sticky="w", pady=6, padx=12)

        # Phone Number
        tk.Label(form_box, text="Phone Number *", font=("Segoe UI", 10, "bold"), bg="#F8F9FA", fg="#002147").grid(row=1, column=0, sticky="w", pady=6)
        self.reg_phone = ttk.Entry(form_box, width=42)
        self.reg_phone.grid(row=1, column=1, sticky="w", pady=6, padx=12)

        # Email
        tk.Label(form_box, text="Email Address (Optional)", font=("Segoe UI", 10), bg="#F8F9FA", fg="#333333").grid(row=2, column=0, sticky="w", pady=6)
        self.reg_email = ttk.Entry(form_box, width=42)
        self.reg_email.grid(row=2, column=1, sticky="w", pady=6, padx=12)

        # Subscription Package Dropdown
        tk.Label(form_box, text="Membership Plan *", font=("Segoe UI", 10, "bold"), bg="#F8F9FA", fg="#002147").grid(row=3, column=0, sticky="w", pady=6)
        self.reg_plan_var = tk.StringVar()
        self.reg_plan_combo = ttk.Combobox(form_box, textvariable=self.reg_plan_var, state="readonly", width=40)
        self.reg_plan_combo.grid(row=3, column=1, sticky="w", pady=6, padx=12)

        # Start Date
        tk.Label(form_box, text="Start Date * (YYYY-MM-DD)", font=("Segoe UI", 10, "bold"), bg="#F8F9FA", fg="#002147").grid(row=4, column=0, sticky="w", pady=6)
        self.reg_date = ttk.Entry(form_box, width=24)
        self.reg_date.insert(0, date.today().strftime("%Y-%m-%d"))
        self.reg_date.grid(row=4, column=1, sticky="w", pady=6, padx=12)

        # Submit button
        btn_submit = tk.Button(form_box, text="✓ Register & Print Member Pass", font=("Segoe UI", 11, "bold"),
                               bg="#002147", fg="#FFFFFF", activebackground="#0A3A6B", activeforeground="#FFFFFF",
                               relief="flat", padx=20, pady=8, cursor="hand2", command=self.submit_registration)
        btn_submit.grid(row=5, column=1, sticky="w", pady=(16, 6), padx=12)

    # ─── TAB 3: RENEW SUBSCRIPTION ─────────────────────────────────────────
    def _build_renew_tab(self):
        title = tk.Label(self.tab_renew, text="Membership Subscription Renewal", font=("Segoe UI", 14, "bold"), fg="#002147", bg="#FFFFFF")
        title.pack(anchor="w", pady=(0, 4))
        sub = tk.Label(self.tab_renew, text="Lookup an existing member to apply Smart Renewal extension without losing remaining days.", font=("Segoe UI", 9), fg="#7F8C8D", bg="#FFFFFF")
        sub.pack(anchor="w", pady=(0, 18))

        box = tk.Frame(self.tab_renew, bg="#F8F9FA", relief="solid", bd=1, padx=24, pady=20)
        box.pack(anchor="w", fill="x", padx=10)

        # Member Lookup
        tk.Label(box, text="Select Member to Renew *", font=("Segoe UI", 10, "bold"), bg="#F8F9FA", fg="#002147").grid(row=0, column=0, sticky="w", pady=6)
        self.renew_member_var = tk.StringVar()
        self.renew_member_combo = ttk.Combobox(box, textvariable=self.renew_member_var, state="readonly", width=46)
        self.renew_member_combo.grid(row=0, column=1, sticky="w", pady=6, padx=12)
        self.renew_member_combo.bind("<<ComboboxSelected>>", self.on_renew_member_selected)

        # Existing Expiry Info Label
        self.lbl_current_info = tk.Label(box, text="Current Expiration: Select a member above...", font=("Segoe UI", 10, "italic"), bg="#F8F9FA", fg="#555555")
        self.lbl_current_info.grid(row=1, column=1, sticky="w", pady=4, padx=12)

        # Plan Selection
        tk.Label(box, text="Choose Renewal Package *", font=("Segoe UI", 10, "bold"), bg="#F8F9FA", fg="#002147").grid(row=2, column=0, sticky="w", pady=6)
        self.renew_plan_var = tk.StringVar()
        self.renew_plan_combo = ttk.Combobox(box, textvariable=self.renew_plan_var, state="readonly", width=46)
        self.renew_plan_combo.grid(row=2, column=1, sticky="w", pady=6, padx=12)

        # Submit Renewal
        btn_renew = tk.Button(box, text="🔄 Apply Smart Renewal Extension", font=("Segoe UI", 11, "bold"),
                              bg="#27AE60", fg="#FFFFFF", activebackground="#219653", activeforeground="#FFFFFF",
                              relief="flat", padx=20, pady=8, cursor="hand2", command=self.submit_renewal)
        btn_renew.grid(row=3, column=1, sticky="w", pady=(16, 6), padx=12)

    # ─── TAB 4: DAILY ATTENDANCE ──────────────────────────────────────────
    def _build_attendance_tab(self):
        top_bar = tk.Frame(self.tab_attendance, bg="#FFFFFF")
        top_bar.pack(side="top", fill="x", pady=(0, 10))

        tk.Label(top_bar, text="Daily Workout Check-Ins (Synced Live with Website)", font=("Segoe UI", 12, "bold"), fg="#002147", bg="#FFFFFF").pack(side="left")

        tree_frame = tk.Frame(self.tab_attendance, bg="#FFFFFF")
        tree_frame.pack(side="top", fill="both", expand=True)

        cols = ("att_id", "name", "phone", "weight", "height", "session", "checkin_time")
        self.tree_attendance = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        self.tree_attendance.heading("att_id", text="# ID")
        self.tree_attendance.heading("name", text="Member Full Name")
        self.tree_attendance.heading("phone", text="Phone")
        self.tree_attendance.heading("weight", text="Weight (kg)")
        self.tree_attendance.heading("height", text="Height")
        self.tree_attendance.heading("session", text="Workout Session")
        self.tree_attendance.heading("checkin_time", text="Check-In Time")

        self.tree_attendance.column("att_id", width=60, anchor="center")
        self.tree_attendance.column("name", width=190, anchor="w")
        self.tree_attendance.column("phone", width=130, anchor="center")
        self.tree_attendance.column("weight", width=95, anchor="center")
        self.tree_attendance.column("height", width=95, anchor="center")
        self.tree_attendance.column("session", width=180, anchor="w")
        self.tree_attendance.column("checkin_time", width=160, anchor="center")

        v_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree_attendance.yview)
        self.tree_attendance.configure(yscrollcommand=v_scroll.set)
        v_scroll.pack(side="right", fill="y")
        self.tree_attendance.pack(side="left", fill="both", expand=True)

    # ─── TAB 5: AUDIT LEDGER ──────────────────────────────────────────────
    def _build_ledger_tab(self):
        tree_frame = tk.Frame(self.tab_ledger, bg="#FFFFFF")
        tree_frame.pack(side="top", fill="both", expand=True)

        cols = ("r_id", "name", "plan", "date", "old_exp", "new_exp", "amount")
        self.tree_ledger = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        self.tree_ledger.heading("r_id", text="Receipt #")
        self.tree_ledger.heading("name", text="Member Name")
        self.tree_ledger.heading("plan", text="Plan Purchased")
        self.tree_ledger.heading("date", text="Payment Date")
        self.tree_ledger.heading("old_exp", text="Prior Expiration")
        self.tree_ledger.heading("new_exp", text="New Expiration")
        self.tree_ledger.heading("amount", text="Amount Paid")

        self.tree_ledger.column("r_id", width=80, anchor="center")
        self.tree_ledger.column("name", width=180, anchor="w")
        self.tree_ledger.column("plan", width=180, anchor="w")
        self.tree_ledger.column("date", width=110, anchor="center")
        self.tree_ledger.column("old_exp", width=120, anchor="center")
        self.tree_ledger.column("new_exp", width=120, anchor="center")
        self.tree_ledger.column("amount", width=130, anchor="e")

        v_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree_ledger.yview)
        self.tree_ledger.configure(yscrollcommand=v_scroll.set)
        v_scroll.pack(side="right", fill="y")
        self.tree_ledger.pack(side="left", fill="both", expand=True)

    def create_status_bar(self):
        status_frame = tk.Frame(self, bg="#EAECEE", height=24, relief="flat", padx=12, pady=4)
        status_frame.pack(side="bottom", fill="x")

        self.status_lbl = tk.Label(status_frame, text=f"Ready • Database: {DB_PATH}", font=("Segoe UI", 8), bg="#EAECEE", fg="#555555")
        self.status_lbl.pack(side="left")

        time_lbl = tk.Label(status_frame, text=f"Today: {date.today().strftime('%B %d, %Y')}", font=("Segoe UI", 8, "bold"), bg="#EAECEE", fg="#002147")
        time_lbl.pack(side="right")

    # ─── DATA REFRESH LOGIC ────────────────────────────────────────────────
    def refresh_all_data(self):
        self.load_pending()
        self.load_plans()
        self.load_members()
        self.load_attendance()
        self.load_ledger()
        self.update_stat_cards()

    def update_stat_cards(self):
        stats = self.manager.get_summary_statistics()
        self.card_total.val_lbl.config(text=str(stats["total"]))
        self.card_active.val_lbl.config(text=str(stats["active"]))
        self.card_expiring.val_lbl.config(text=str(stats["expiring_soon"]))
        self.card_expired.val_lbl.config(text=str(stats["expired"]))
        self.card_pending.val_lbl.config(text=str(stats.get("pending", 0)))

    def load_pending(self):
        for item in self.tree_pending.get_children():
            self.tree_pending.delete(item)

        self.pending_list = self.manager.get_pending_payments(status="PENDING")
        for p in self.pending_list:
            t_disp = p["created_at"][:19].replace("T", " ") if p["created_at"] else ""
            self.tree_pending.insert("", "end", values=(
                f"BUG-P{p['pending_id']:04d}",
                p["full_name"],
                p["phone"],
                p["plan_name"],
                f"{p['amount_due']:,.0f} UGX",
                p["start_date"],
                t_disp
            ))

        # Update tab label with pending count
        count = len(self.pending_list)
        self.notebook.tab(self.tab_pending, text=f"   ⏳ Pending Approvals ({count})   ")
        if count > 0:
            self.card_pending.val_lbl.config(fg="#D35400")
        else:
            self.card_pending.val_lbl.config(fg="#002147")

    def load_plans(self):
        plans = self.manager.get_plans()
        self.plans_cache = {p["plan_id"]: p for p in plans}
        plan_options = [f"{p['plan_id']}: {p['name']} ({p['duration_months']} mo) - {p['price']:,.0f} UGX" for p in plans]
        self.reg_plan_combo["values"] = plan_options
        if plan_options and not self.reg_plan_var.get():
            self.reg_plan_combo.current(0)
        self.renew_plan_combo["values"] = plan_options
        if plan_options and not self.renew_plan_var.get():
            self.renew_plan_combo.current(0)

    def load_members(self):
        self.all_members = self.manager.fetch_members_report(filter_status="ALL")
        self.filter_directory()

        # Update member dropdown in Renew tab
        member_options = [f"{m['member_id']} - {m['full_name']} ({m['phone']})" for m in self.all_members]
        self.renew_member_combo["values"] = member_options

    def filter_directory(self):
        for item in self.tree_members.get_children():
            self.tree_members.delete(item)

        search_query = self.search_var.get().strip().lower()
        status_filter = self.status_filter_var.get()

        for m in self.all_members:
            if status_filter != "ALL" and m["status"] != status_filter:
                continue

            # Text filter
            name = m["full_name"].lower()
            phone = m["phone"].lower()
            plan = m["plan_name"].lower()
            formatted_id = f"BUG-{m['member_id']:04d}".lower()

            if search_query and (search_query not in name and search_query not in phone and search_query not in plan and search_query not in formatted_id):
                continue

            days_str = f"{m['days_remaining']} days" if m["days_remaining"] >= 0 else f"{abs(m['days_remaining'])} days ago"
            item_id = self.tree_members.insert("", "end", values=(
                f"BUG-{m['member_id']:04d}",
                m["full_name"],
                m["phone"],
                m["plan_name"],
                m["start_date"],
                m["expiration_date"],
                days_str,
                m["status"]
            ), tags=(m["status"],))

    def load_attendance(self):
        for item in self.tree_attendance.get_children():
            self.tree_attendance.delete(item)

        try:
            with self.db_mgr.connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT attendance_id, full_name, phone, weight_kg, height_cm, session, checkin_time
                    FROM attendance
                    ORDER BY attendance_id DESC
                    LIMIT 100
                """)
                rows = cursor.fetchall()

            for r in rows:
                t_disp = r["checkin_time"][:19].replace("T", " ") if r["checkin_time"] else ""
                self.tree_attendance.insert("", "end", values=(
                    r["attendance_id"],
                    r["full_name"],
                    r["phone"] or "N/A",
                    f"{r['weight_kg']} kg" if r["weight_kg"] else "—",
                    r["height_cm"] or "—",
                    r["session"] or "General Gym",
                    t_disp
                ))
        except Exception:
            pass

    def load_ledger(self):
        for item in self.tree_ledger.get_children():
            self.tree_ledger.delete(item)

        logs = self.manager.get_renewal_history()
        for log in logs:
            old_exp = log["old_expiration_date"] if log["old_expiration_date"] else "New Sign-Up"
            self.tree_ledger.insert("", "end", values=(
                f"#{log['renewal_id']:04d}",
                log["full_name"],
                log["plan_name"],
                log["renewal_date"],
                old_exp,
                log["new_expiration_date"],
                f"{log['amount_paid']:,.0f} UGX"
            ))

    def auto_refresh_loop(self):
        """Silently reloads database tables every 5 seconds so online website registrations show up live."""
        try:
            self.refresh_all_data()
        except Exception:
            pass
        self.after(5000, self.auto_refresh_loop)

    # ─── ACTION HANDLERS ───────────────────────────────────────────────────
    def submit_registration(self):
        name = self.reg_name.get().strip()
        phone = self.reg_phone.get().strip()
        email = self.reg_email.get().strip()
        plan_str = self.reg_plan_var.get()
        start_date_str = self.reg_date.get().strip()

        if not name or len(name) < 2:
            messagebox.showerror("Validation Error", "Please enter a valid member name.")
            return
        if not phone or len(phone) < 7:
            messagebox.showerror("Validation Error", "Please enter a valid contact phone number.")
            return
        if not plan_str:
            messagebox.showerror("Validation Error", "Please select a membership package.")
            return

        try:
            plan_id = int(plan_str.split(":")[0])
        except Exception:
            messagebox.showerror("Validation Error", "Invalid plan selection.")
            return

        try:
            start_date_obj = DateHelper.parse_date(start_date_str)
        except Exception:
            messagebox.showerror("Validation Error", "Invalid date format. Use YYYY-MM-DD.")
            return

        success, msg = self.manager.register_member(name, phone, email, plan_id, start_date_obj)
        if success:
            messagebox.showinfo("Registration Successful", msg)
            self.reg_name.delete(0, "end")
            self.reg_phone.delete(0, "end")
            self.reg_email.delete(0, "end")
            self.refresh_all_data()
            self.notebook.select(self.tab_directory)
        else:
            messagebox.showerror("Registration Failed", msg)

    def on_renew_member_selected(self, event=None):
        sel = self.renew_member_var.get()
        if not sel:
            return
        member_id = int(sel.split("-")[0].strip())
        member = next((m for m in self.all_members if m["member_id"] == member_id), None)
        if member:
            self.lbl_current_info.config(
                text=f"Plan: {member['plan_name']} | Current Expiration: {member['expiration_date']} ({member['status']})",
                fg="#27AE60" if member["status"] == "ACTIVE" else "#C0392B"
            )

    def submit_renewal(self):
        sel_member = self.renew_member_var.get()
        sel_plan = self.renew_plan_var.get()

        if not sel_member:
            messagebox.showerror("Validation Error", "Please select a member to renew.")
            return
        if not sel_plan:
            messagebox.showerror("Validation Error", "Please select a renewal package.")
            return

        member_id = int(sel_member.split("-")[0].strip())
        plan_id = int(sel_plan.split(":")[0].strip())

        success, msg = self.manager.renew_membership(member_id, plan_id, date.today())
        if success:
            messagebox.showinfo("Renewal Applied", msg)
            self.refresh_all_data()
            self.notebook.select(self.tab_directory)
        else:
            messagebox.showerror("Renewal Failed", msg)


if __name__ == "__main__":
    app = GymDesktopApp()
    app.mainloop()
