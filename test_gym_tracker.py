#!/usr/bin/env python3
"""
Unit tests for Bugema University Gym Membership & Expiration Tracker core logic.
Verifies date math, smart renewal transitions, and account status classifications.
"""

import os
import sys
import unittest
import tempfile
import sqlite3
from datetime import date

# Import classes to be tested from gym_tracker
from gym_tracker import DateHelper, DatabaseManager, MembershipManager

class TestDateCalculations(unittest.TestCase):
    """Verifies calendar month additions including edge cases (leap years and month overflows)."""
    
    def test_standard_addition(self):
        # Add 1 month to standard date
        d = date(2026, 1, 15)
        self.assertEqual(DateHelper.add_months(d, 1), date(2026, 2, 15))
        
        # Add 3 months
        d2 = date(2026, 5, 10)
        self.assertEqual(DateHelper.add_months(d2, 3), date(2026, 8, 10))

    def test_month_overflow_bounds(self):
        # Adding 1 month to Jan 31 in standard year -> Feb 28
        d1 = date(2026, 1, 31)
        self.assertEqual(DateHelper.add_months(d1, 1), date(2026, 2, 28))
        
        # Adding 1 month to Aug 31 -> Sep 30
        d2 = date(2026, 8, 31)
        self.assertEqual(DateHelper.add_months(d2, 1), date(2026, 9, 30))

    def test_leap_year_bounds(self):
        # Adding 1 month to Jan 31 in leap year (2024) -> Feb 29
        d = date(2024, 1, 31)
        self.assertEqual(DateHelper.add_months(d, 1), date(2024, 2, 29))


class TestSmartRenewalAndStatus(unittest.TestCase):
    """Verifies relational database logic, status classification, and smart renewal rules."""
    
    def setUp(self):
        # Use a temporary SQLite file for testing
        self.db_fd, self.db_path = tempfile.mkstemp()
        self.db = DatabaseManager(self.db_path)
        self.manager = MembershipManager(self.db)
        
        # Manually seed subscription plans for testing
        with self.db.connection() as conn:
            conn.execute("INSERT INTO plans (plan_id, name, duration_months, price) VALUES (1, 'Monthly', 1, 50000.0)")
            conn.execute("INSERT INTO plans (plan_id, name, duration_months, price) VALUES (2, 'Quarterly', 3, 130000.0)")
            conn.commit()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_register_member(self):
        res = self.manager.register_member(
            full_name="Jane Smith",
            phone="0779999999",
            email="jane.smith@email.com",
            plan_id=1,
            start_date_str="2026-08-01"
        )
        self.assertEqual(res['full_name'], "Jane Smith")
        # 1 Month duration from 2026-08-01 -> 2026-09-01
        self.assertEqual(res['expiration_date'], "2026-09-01")

    def test_smart_renewal_before_expiry(self):
        # Register a member with expiry on 2026-09-01
        res = self.manager.register_member(
            full_name="John Active",
            phone="0772222222",
            email="active@email.com",
            plan_id=1,
            start_date_str="2026-08-01"
        )
        member_id = res['member_id']
        
        # Renew BEFORE expiry (on 2026-08-27)
        # Expiration is 2026-09-01. Since 2026-08-27 <= 2026-09-01:
        # New start date should extend from old expiration: 2026-09-01.
        # New expiration date: 2026-09-01 + 1 month = 2026-10-01.
        renew_res = self.manager.renew_membership(
            member_id=member_id,
            plan_id=1,
            renewal_date_str="2026-08-27"
        )
        self.assertEqual(renew_res['renew_type'], "EXTENSION")
        self.assertEqual(renew_res['new_start_date'], "2026-09-01")
        self.assertEqual(renew_res['new_expiration_date'], "2026-10-01")

    def test_smart_renewal_after_expiry(self):
        # Register a member with expiry on 2026-08-20
        res = self.manager.register_member(
            full_name="John Expired",
            phone="0773333333",
            email="expired@email.com",
            plan_id=1,
            start_date_str="2026-07-20"
        )
        member_id = res['member_id']
        
        # Renew AFTER expiry (on 2026-08-27)
        # Expiration is 2026-08-20. Since 2026-08-27 > 2026-08-20:
        # New start date should extend from transaction date: 2026-08-27.
        # New expiration date: 2026-08-27 + 1 month = 2026-09-27.
        renew_res = self.manager.renew_membership(
            member_id=member_id,
            plan_id=1,
            renewal_date_str="2026-08-27"
        )
        self.assertEqual(renew_res['renew_type'], "NEW_START")
        self.assertEqual(renew_res['new_start_date'], "2026-08-27")
        self.assertEqual(renew_res['new_expiration_date'], "2026-09-27")

    def test_status_categorization(self):
        # Register three members representing Active, Expiring Soon, Expired relative to 2026-08-27
        # Active: Expiry 2026-11-10
        m1 = self.manager.register_member("M1 Active", "0770000001", None, 2, "2026-08-10")
        
        # Expiring Soon (Expires in 3 days on 2026-08-30)
        m2 = self.manager.register_member("M2 Soon", "0770000002", None, 2, "2026-05-30")
        
        # Expired (Expired on 2026-08-20)
        m3 = self.manager.register_member("M3 Expired", "0770000003", None, 1, "2026-07-20")
        
        # Fetch report on 2026-08-27 with threshold 7 days
        report = self.manager.fetch_members_report(current_date_str="2026-08-27", custom_threshold=7)
        
        # Ensure we have correct classification
        member_statuses = {item['full_name']: item['status'] for item in report}
        self.assertEqual(member_statuses["M1 Active"], "ACTIVE")
        self.assertEqual(member_statuses["M2 Soon"], "EXPIRING SOON")
        self.assertEqual(member_statuses["M3 Expired"], "EXPIRED")
        
        # Verify days remaining math
        m2_report = next(item for item in report if item['full_name'] == "M2 Soon")
        self.assertEqual(m2_report['days_remaining'], 3)
        
        m3_report = next(item for item in report if item['full_name'] == "M3 Expired")
        self.assertEqual(m3_report['days_remaining'], -7)


if __name__ == '__main__':
    unittest.main()
