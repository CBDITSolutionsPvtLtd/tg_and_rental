# Copyright (c) 2025, Mack and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate, today, add_days, cint
from typing import TYPE_CHECKING
from frappe.model.mapper import get_mapped_doc
from erpnext.controllers.accounts_controller import get_item_details
from calendar import monthrange
import math
import calendar
import json


class TGAndRentalBill(Document):
    if TYPE_CHECKING:
        from frappe.types import DF
        naming_series: DF.Data
        type: DF.Literal["Rental", "TG"]
        customer: DF.Link
        agreement_no: DF.Link
        posting_date: DF.Date
        due_date: DF.Date | None
        bill_from: DF.Date | None
        bill_to: DF.Date | None
        cnt_start_dt: DF.Date | None
        cnt_end_dt: DF.Date | None
        copies: DF.Table  # child table → Rented Items Table
        taxes: DF.Table
        total_copies: DF.Int | None
        total_current_copy: DF.Int | None
        total_free_copy: DF.Int | None
        total_net_copy: DF.Int | None
        total_amt: DF.Currency | None
        actual_total: DF.Currency | None
        monthly_fix_amt: DF.Currency | None
        comm_amt_pm: DF.Currency | None
        total_tax: DF.Currency | None
        grand_total: DF.Currency | None
        status: DF.Literal["Draft", "Billed (Not Invoiced)", "Overdue (Not Invoiced)", "Unpaid", "Paid", "Partly Paid", "Overdue", "Cancelled"]
        month: DF.Literal["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
        year: DF.Int | None
        prev_total: DF.Currency | None
        prev_paid_amount: DF.Currency | None
        prev_balance: DF.Currency | None
        outstanding_amount: DF.Currency | None
        paid_amt: DF.Currency | None
        after_due_amount: DF.Currency | None
        enable_rounded_total: DF.Check
        rounded_total: DF.Currency | None

    def get_indicator(self):
        if self.status == "Billed (Not Invoiced)":
            return ("Billed (Not Invoiced)", "blue", "status,=,Billed (Not Invoiced)")
        elif self.status == "Overdue (Not Invoiced)":
            return ("Overdue (Not Invoiced)", "red", "status,=,Overdue (Not Invoiced)")
        elif self.status == "Unpaid":
            return ("Unpaid", "orange", "status,=,Unpaid")
        elif self.status == "Overdue":
            return ("Overdue", "red", "status,=,Overdue")
        elif self.status == "Partly Paid":
            return ("Partly Paid", "yellow", "status,=,Partly Paid")
        elif self.status == "Paid":
            return ("Paid", "green", "status,=,Paid")
        elif self.status == "Cancelled":
            return ("Cancelled", "black", "status,=,Cancelled")
        elif self.status == "Draft":
            return ("Draft", "purple", "status,=,Draft")
        else:
            return (self.status or "Unknown", "gray", f"status,=,{self.status}")

    
    
    # ---------------- CORE VALIDATION ---------------- #
    def validate(self):
        self._recalculate_all_rows()
        self._calculate_totals()

        for row in self.copies or []:
            if (row.current_cc or 0) < (row.previous_cc or 0):
                frappe.throw(f"Row #{row.idx}: Current CC ({row.current_cc}) cannot be less than Previous CC ({row.previous_cc}) for item {row.item or ''}.")

        if self.posting_date and self.due_date:
            if getdate(self.due_date) < getdate(self.posting_date):
                frappe.throw("Due Date cannot be before Posting Date.")


    def before_save(self):
        if not self.bill_from:
            today_dt = getdate(today())
            first_day = today_dt.replace(day=1)
            last_day_num = monthrange(today_dt.year, today_dt.month)[1]
            last_day = today_dt.replace(day=last_day_num)
            self.bill_from = first_day
            self.bill_to = last_day

        if not self.manual_previous_cc:
            for row in self.copies:
                row.previous_cc = self._get_previous_cc(row.item)

        if not self.due_date and self.posting_date:
            settings = frappe.get_single('Rent TG Setting')
            bill_due_days = cint(settings.bill_due_days) if settings and hasattr(settings, 'bill_due_days') else 0
            if bill_due_days:
                self.due_date = add_days(self.posting_date, bill_due_days)

        # NEW: set previous bill totals
        self._set_previous_bill_values()
            
        if self.bill_from:
            bill_from_date = getdate(self.bill_from)
            self.month = calendar.month_name[bill_from_date.month]
            self.year = bill_from_date.year
            # Ensure bill_to covers the full month if not already set
            if not self.bill_to:
                last_day_num = monthrange(bill_from_date.year, bill_from_date.month)[1]
                self.bill_to = bill_from_date.replace(day=last_day_num)

        if self.bill_to and self.bill_from:
            if getdate(self.bill_to) < getdate(self.bill_from):
                frappe.throw("Bill To date cannot be before Bill From date.")

    def on_submit(self):
        """Update Rent TG Agreement child table safely on submit."""
        if self.agreement_no:
            frappe.db.set_value(
                "Rent TG Agreement",
                self.agreement_no,
                "copies_used",
                self.total_current_copy or 0,
                update_modified=False
            )
        self.update_status()
        self.db_update()

    def on_cancel(self):
        """Roll back agreement references and recompute subsequent bills."""
        self._recompute_subsequent_bills()
        self.status = "Cancelled"
        self.db_update()
    
    def on_update_after_submit(self):
        """Called when document is updated after submit."""
        self.update_status()

    # ________Status + OutStanding change Code(new)________
    def update_status(self):
        if self.docstatus != 1:
            return

        today_dt = getdate(today())
        due_dt = getdate(self.due_date) if self.due_date else None

        si = frappe.db.get_value(
            "Sales Invoice",
            {"custom_tg_rent_bill": self.name, "docstatus": 1},
            ["name", "status", "outstanding_amount", "grand_total", "rounded_total"],
            as_dict=True
        )

        if si:
            outstanding = flt(si.outstanding_amount or 0)
            grand_total = flt(si.rounded_total or si.grand_total or 0)

            self.status = si.status
            self.outstanding_amount = outstanding
            self.paid_amt = max(0, grand_total - outstanding)
        else:
            if due_dt and due_dt < today_dt:
                self.status = "Overdue (Not Invoiced)"
                self.outstanding_amount = self.after_due_amount or self.grand_total or 0
            else:
                self.status = "Billed (Not Invoiced)"
                self.outstanding_amount = self.grand_total or 0
            self.paid_amt = 0
            
    def _set_previous_bill_values(self):
        """Set prev_total, prev_paid_amount, prev_balance from last bill of same agreement."""
        self.prev_total = 0.0
        self.prev_paid_amount = 0.0
        self.prev_balance = 0.0

        if not self.agreement_no or not self.bill_from:
            return

        prev = frappe.db.sql(
			"""
			SELECT 
				COALESCE(grand_total, 0) as grand_total,
				COALESCE(paid_amt, 0) as paid_amt,
				COALESCE(outstanding_amount, 0) as outstanding_amount
			FROM `tabTG And Rental Bill`
			WHERE agreement_no = %s
			  AND docstatus = 1
			  AND bill_from < %s
			  AND name != %s
			ORDER BY bill_from DESC, creation DESC
			LIMIT 1
			""",
			(self.agreement_no, self.bill_from, self.name or ""),
			as_dict=True
		)

        if prev and len(prev) > 0:
            self.prev_total = flt(prev[0].get('grand_total', 0))
            self.prev_paid_amount = flt(prev[0].get('paid_amt', 0))
            self.prev_balance = flt(prev[0].get('outstanding_amount', 0))

    def _recalculate_all_rows(self):
        total_copies_sum = 0
        total_current_copy_sum = 0
        total_free_copy_sum = 0
        total_net_copy_sum = 0
        total_amt_sum = 0.0

        for row in self.copies or []:
            self._recalculate_row(row)
            total_copies_sum += row.total_copies or 0
            total_current_copy_sum += row.current_cc or 0
            total_free_copy_sum += row.free_copies or 0
            total_net_copy_sum += row.net_copy or 0
            total_amt_sum += flt(row.amount)

        # update parent totals
        self.total_copies = total_copies_sum
        self.total_current_copy = total_current_copy_sum
        self.total_free_copy = total_free_copy_sum
        self.total_net_copy = total_net_copy_sum
        self.total_amt = total_amt_sum

    def _recalculate_row(self, row):
        previous = row.previous_cc or 0
        current = row.current_cc or 0
        free = row.free_copies or 0
        rate = row.rate or 0

        row.total_copies = current - previous
        row.net_copy = row.total_copies - free
        row.amount = flt(row.net_copy) * flt(rate)

    def _calculate_totals(self):
        total_amt = self.total_amt or 0
        monthly_fix_amt = self.monthly_fix_amt or 0
        comm_amt_pm = self.comm_amt_pm or 0

        if monthly_fix_amt == 0 and comm_amt_pm > 0:
            if total_amt < comm_amt_pm:
                self.actual_total = comm_amt_pm
            else:
                self.actual_total = total_amt

        elif monthly_fix_amt > 0 and comm_amt_pm == 0:
            if total_amt < 0:
                self.actual_total = monthly_fix_amt
            else:
                self.actual_total = monthly_fix_amt + total_amt

        else:
            self.actual_total = total_amt

        # ---- taxes ----
        total_tax = 0.0
        for row in self.taxes or []:
            row.tax_amount = flt(self.actual_total) * flt(row.tax_rate) / 100
            total_tax += row.tax_amount

        self.total_tax = total_tax
        self.grand_total = (self.actual_total or 0) + total_tax

        if self.enable_rounded_total:
            self.rounded_total = math.floor(self.grand_total + 0.5)  # standard round-half-up
        else:
            self.rounded_total = self.grand_total

        overdue_charge_percent = flt(frappe.db.get_single_value("Rent TG Setting", "overdue_charge_percent") or 0)
        if self.grand_total:
            self.after_due_amount = flt(self.grand_total) + (flt(self.grand_total) * overdue_charge_percent / 100)
        else:
            self.after_due_amount = 0

    # ---------------- HELPERS ---------------- #
    def _get_previous_cc(self, item):
        """
        Find latest submitted bill before this bill_from date for same agreement+item.
        Returns 0 if no previous bill exists (first bill for this item).
        """
        if not self.bill_from or not self.agreement_no:
            return 0
        
        latest = frappe.db.sql(
            """
            SELECT c.current_cc
            FROM `tabTG And Rental Bill` b
            JOIN `tabRented Items Table` c ON c.parent = b.name
            WHERE b.docstatus = 1
              AND b.agreement_no = %s
              AND c.item = %s
              AND b.bill_from < %s
            ORDER BY b.bill_from DESC, b.creation DESC
            LIMIT 1
            """,
            (self.agreement_no, item, self.bill_from),
            as_dict=True
        )
        return latest[0].current_cc if latest else 0

    # def _update_agreement_references(self, set_on_cancel=False):
    #     for row in self.copies:
    #         agreement_items = frappe.get_all(
    #             "Agreement Items Table",
    #             filters={"parent": self.agreement_no, "item": row.item},
    #             fields=["name", "prev_cc", "bill_no"]
    #         )
    #         for ait in agreement_items:
    #             if set_on_cancel:
    #                 if ait.bill_no == self.name:
    #                     frappe.db.set_value(
    #                         "Agreement Items Table",
    #                         ait.name,
    #                         {"prev_cc": row.previous_cc, "bill_no": None},
    #                         update_modified=False
    #                     )
    #             else:
    #                 frappe.db.set_value(
    #                     "Agreement Items Table",
    #                     ait.name,
    #                     {"prev_cc": row.current_cc, "bill_no": self.name},
    #                     update_modified=False
    #                 )

    def _recompute_subsequent_bills(self):
        """Recompute previous_cc for all submitted bills after this bill_from date."""
        if not self.bill_from:
            return
            
        subsequent_bills = frappe.db.sql(
            """
            SELECT name FROM `tabTG And Rental Bill`
            WHERE docstatus = 1
              AND agreement_no = %s
              AND bill_from > %s
            ORDER BY bill_from ASC, creation ASC
            """,
            (self.agreement_no, self.bill_from),
            as_dict=True
        )

        for sb in subsequent_bills:
            bill = frappe.get_doc("TG And Rental Bill", sb.name)
            bill.before_save()  # recompute prev_cc
            bill.save(ignore_permissions=True)

# ---------------- INVOICE SYNC ---------------- #
def update_bill_status_from_invoice(doc, method):
    """Sync TG And Rental Bill when Sales Invoice changes."""
    bill_name = doc.custom_tg_rent_bill
    if not bill_name:
        return

    try:
        bill = frappe.get_doc("TG And Rental Bill", bill_name)
    except frappe.DoesNotExistError:
        return

    if bill.docstatus != 1:
        return

    if doc.docstatus == 1:

        outstanding = flt(doc.outstanding_amount or 0)
        grand_total = flt(doc.rounded_total or doc.grand_total or 0)
        # Mirror SI status
        bill.status = doc.status
        bill.outstanding_amount = outstanding
        bill.paid_amt = max(0, grand_total - outstanding)
        bill.db_update()
    else:
        # If SI cancelled/deleted → fall back to Condition 1
        bill.update_status()
        bill.db_update()

def sync_bills_from_payment(doc, method):
    """When a Payment Entry is submitted/cancelled, re-sync linked Sales Invoices → Bills."""
    for ref in doc.references or []:
        if ref.reference_doctype == "Sales Invoice" and ref.reference_name:
            try:
                si = frappe.get_doc("Sales Invoice", ref.reference_name)
            except frappe.DoesNotExistError:
                continue

            if si.custom_tg_rent_bill:
                update_bill_status_from_invoice(si, "on_update_after_submit")

# ---------------- WHITELIST ---------------- #
@frappe.whitelist()
def get_previous_cc(agreement_no, item, bill_from):
    if not agreement_no or not item or not bill_from:
        return 0
    
    latest = frappe.db.sql(
        """
        SELECT c.current_cc
        FROM `tabTG And Rental Bill` b
        JOIN `tabRented Items Table` c ON c.parent = b.name
        WHERE b.docstatus = 1
          AND b.agreement_no = %s
          AND c.item = %s
          AND b.bill_from < %s
        ORDER BY b.bill_from DESC, b.creation DESC
        LIMIT 1
        """,
        (agreement_no, item, bill_from),
        as_dict=True
    )
    return latest[0].current_cc if latest else 0

@frappe.whitelist()
def get_previous_cc_batch(agreement_no, bill_from, items_json):
    """Return map of item → previous_cc for given agreement and bill_from."""
    if not agreement_no or not bill_from:
        return {}
    try:
        items = json.loads(items_json)
    except Exception:
        return {}

    if not items:
        return {}

    placeholders = ','.join(['%s'] * len(items))
    result = frappe.db.sql(
        f"""
        SELECT c.item, c.current_cc
        FROM `tabTG And Rental Bill` b
        JOIN `tabRented Items Table` c ON c.parent = b.name
        WHERE b.docstatus = 1
          AND b.agreement_no = %s
          AND c.item IN ({placeholders})
          AND b.bill_from < %s
          AND b.bill_from = (
            SELECT MAX(b2.bill_from)
            FROM `tabTG And Rental Bill` b2
            WHERE b2.agreement_no = b.agreement_no
              AND b2.docstatus = 1
              AND b2.bill_from < %s
          )
        """,
        [agreement_no] + items + [bill_from, bill_from],
        as_dict=True,
    )
    
    prev_map = {r.item: flt(r.current_cc) for r in result}
    return {i: prev_map.get(i, 0) for i in items}

@frappe.whitelist()
def get_previous_bill_values(agreement_no, bill_from, name=None):
	"""Fetch previous bill payment details for immediate display in form."""
	if not agreement_no or not bill_from:
		return {
			"prev_total": 0.0,
			"prev_paid_amount": 0.0,
			"prev_balance": 0.0
		}

	prev = frappe.db.sql(
		"""
		SELECT 
			COALESCE(grand_total, 0) as grand_total,
			COALESCE(paid_amt, 0) as paid_amt,
			COALESCE(outstanding_amount, 0) as outstanding_amount
		FROM `tabTG And Rental Bill`
		WHERE agreement_no = %s
		  AND docstatus = 1
		  AND bill_from < %s
		  AND name != %s
		ORDER BY bill_from DESC, creation DESC
		LIMIT 1
		""",
		(agreement_no, bill_from, name or ""),
		as_dict=True
	)

	if prev and len(prev) > 0:
		return {
			"prev_total": flt(prev[0].get('grand_total', 0)),
			"prev_paid_amount": flt(prev[0].get('paid_amt', 0)),
			"prev_balance": flt(prev[0].get('outstanding_amount', 0))
		}

	return {
		"prev_total": 0.0,
		"prev_paid_amount": 0.0,
		"prev_balance": 0.0
	}

@frappe.whitelist()
def make_sales_invoice(source_name, target_doc=None):

    existing_submitted_si = frappe.db.get_value("Sales Invoice", {"custom_tg_rent_bill": source_name, "docstatus": 1}, "name")
    if existing_submitted_si:
        frappe.throw(f"Sales Invoice {existing_submitted_si} is already submitted for this Bill.")
    
    def set_missing_values(source, target, source_parent=None):
        target.custom_tg_rent_bill = source.name
        target.customer = source.customer
        target.posting_date = source.posting_date
        target.due_date = source.due_date
        target.set_posting_time = True
        target.disable_rounded_total = 0 if source.enable_rounded_total else 1

        if source.customer_address:
            target.customer_address = source.customer_address
        else:
            # fallback: get the primary address of this customer
            customer_address = frappe.db.get_value(
                "Address",
                {"is_primary_address": 1, "links.link_doctype": "Customer", "links.link_name": source.customer},
                "name"
            ) or frappe.db.get_value(
                "Dynamic Link",
                {"link_doctype": "Customer", "link_name": source.customer, "parenttype": "Address"},
                "parent"
            )
            if customer_address:
                target.customer_address = customer_address

        if source.contact:
            # Validate contact belongs to same customer
            valid_contact = frappe.db.exists(
                "Dynamic Link",
                {
                    "link_doctype": "Customer",
                    "link_name": source.customer,
                    "parenttype": "Contact",
                    "parent": source.contact
                }
            )
            if valid_contact:
                target.contact_person = source.contact
            else:
                target.contact_person = None
        else:
            # fallback: pick the primary or first linked contact
            contact = frappe.db.get_value(
                "Contact",
                {"is_primary_contact": 1, "links.link_doctype": "Customer", "links.link_name": source.customer},
                "name"
            ) or frappe.db.get_value(
                "Dynamic Link",
                {"link_doctype": "Customer", "link_name": source.customer, "parenttype": "Contact"},
                "parent"
            )
            if contact:
                target.contact_person = contact

        if target.customer and target.company:
            customer_doc = frappe.get_doc("Customer", target.customer)
            # Use customer's default receivable account or fallback to company default
            debit_to_account = customer_doc.get("default_receivable_account") or \
                frappe.get_cached_value("Company", target.company, "default_receivable_account")

            if debit_to_account:
                target.debit_to = debit_to_account

        def add_invoice_item(item_code, qty, rate):
            # Defensive data handling
            qty = qty if qty is not None else 0
            try:
                qty = float(qty)
            except Exception:
                qty = 0
            try:
                rate = float(rate)
            except Exception:
                rate = 0

            # Adjust qty and rate per business logic
            if qty < 0:
                qty = abs(qty)
                rate = -rate
            elif qty == 0:
                qty = 1
                rate = 0

            args = {
                "item_code": item_code,
                "company": target.company,
                "customer": target.customer,
                "qty": qty,
                "doctype": target.doctype,
                "currency": target.currency,
            }
            item_details = get_item_details(args) or {}

            row = target.append("items", {
                "item_code": item_code,
                "item_name": item_details.get("item_name"),
                "description": item_details.get("description"),
                "uom": item_details.get("uom"),
                "income_account": item_details.get("income_account"),
                "cost_center": item_details.get("cost_center"),
                "qty": qty,
            })
            row.rate = flt(rate)
            return row


        monthly_fix_amt = float(source.monthly_fix_amt or 0)
        comm_amt_pm = float(source.comm_amt_pm or 0)
        total_amt = float(source.total_amt or 0)

        if monthly_fix_amt == 0 and comm_amt_pm > 0:
            if total_amt < comm_amt_pm:
                # Only Monthly Commitment Amount
                add_invoice_item("Monthly Commitment Amount", 1, comm_amt_pm)
            else:
                # Add items from copies table
                for row in source.copies:
                    if not row.item:
                        continue
                    qty = row.net_copy or 0
                    rate = row.rate or 0
                    if qty < 0:
                        qty = abs(qty)
                        rate = -rate
                    add_invoice_item(row.item, qty, rate)
        elif monthly_fix_amt > 0 and comm_amt_pm == 0:
            if total_amt < 0:
                # Only Monthly Fixed Rent
                add_invoice_item("Monthly Fixed Rent", 1, monthly_fix_amt)
            else:
                # Add all copies AND extra Monthly Fixed Rent
                add_invoice_item("Monthly Fixed Rent", 1, monthly_fix_amt)
                for row in source.copies:
                    if not row.item:
                        continue
                    qty = row.net_copy or 0
                    rate = row.rate or 0
                    if qty < 0:
                        qty = abs(qty)
                        rate = -rate
                    add_invoice_item(row.item, qty, rate)
        else:
            # Fallback: Add items from copies table
            for row in source.copies:
                if not row.item:
                    continue
                qty = row.net_copy or 0
                rate = row.rate or 0
                if qty < 0:
                    qty = abs(qty)
                    rate = -rate
                add_invoice_item(row.item, qty, rate)


        # --- Map taxes from Bill to Sales Invoice taxes table ---
        if hasattr(target, "taxes"):
            target.set("taxes", [])  # clear existing taxes
            for bill_tax in (source.taxes or []):
                # Lookup account heads for CGST and SGST from Rent TG Setting or fallback empty
                if bill_tax.type == "CGST":
                    account_head = frappe.db.get_single_value("Rent TG Setting", "cgst_account_head") or ""
                elif bill_tax.type == "SGST":
                    account_head = frappe.db.get_single_value("Rent TG Setting", "sgst_account_head") or ""
                elif bill_tax.type == "IGST":
                    account_head = frappe.db.get_single_value("Rent TG Setting", "igst_account_head") or ""
                elif bill_tax.type == "TDS":
                    account_head = frappe.db.get_single_value("Rent TG Setting", "tds_account_head") or ""
                else:
                    account_head = ""

                if account_head:
                    target.append("taxes", {
                        "charge_type": "On Net Total",
                        "account_head": account_head,
                        "rate": bill_tax.tax_rate or 0,
                        "description": bill_tax.type
                    })

    # doc = get_mapped_doc(
    #     "TG And Rental Bill",
    #     source_name,
    #     {"TG And Rental Bill": {"doctype": "Sales Invoice"}},
    #     target_doc,
    #     set_missing_values
    # )
    doc = get_mapped_doc(
        "TG And Rental Bill",
        source_name,
        {
            "TG And Rental Bill": {
                "doctype": "Sales Invoice",
                "postprocess": set_missing_values
            }
        },
        target_doc
    )
    return doc


def daily_update_bill_status():
    bills = frappe.get_all("TG And Rental Bill", filters={"docstatus": 1}, pluck="name")
    for name in bills:
        try:
            bill = frappe.get_doc("TG And Rental Bill", name)
            bill.update_status()

            if bill.paid_amt and bill.paid_amt < 0:
                bill.paid_amt = 0
                
            bill.db_update()
        except Exception as e:
            frappe.log_error(f"Error updating bill {name}: {str(e)}", "Bill Status Update Error")
