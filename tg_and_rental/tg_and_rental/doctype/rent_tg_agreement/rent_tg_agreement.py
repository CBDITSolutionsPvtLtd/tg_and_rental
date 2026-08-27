import frappe
from frappe.model.document import Document
from frappe.utils import getdate, today, flt
from dateutil.relativedelta import relativedelta
from typing import TYPE_CHECKING

class RentTGAgreement(Document):
    # type hints
    if TYPE_CHECKING:
        from frappe.types import DF
        status: DF.Literal["Draft", "Active", "Expired", "Cancelled"]
        start_date: DF.Date | None
        end_date: DF.Date | None
        time_duration: DF.Int | None
        time_unit: DF.Literal["Day", "Week", "Month", "Year"] | None
        agreement_type: DF.Literal["TG", "Rental"] | None
        comm_copies_pm: DF.Int | None
        comm_rate_pc: DF.Currency | None
        comm_amt_pm: DF.Currency | None  # Committed Amount Per Month

    def get_indicator(self):
        if self.status == "Active":
            return ("Active", "green", "status,=,Active")
        elif self.status == "Expired":
            return ("Expired", "red", "status,=,Expired")
        elif self.status == "Cancelled":
            return ("Cancelled", "gray", "status,=,Cancelled")
        else:  # Draft
            return ("Draft", "orange", "status,=,Draft")

    def validate(self):
        self.compute_end_date()

        if self.docstatus == 0:
            self.status = "Draft"

        if self.start_date and self.end_date and getdate(self.end_date) < getdate(self.start_date):
            frappe.throw("End Date cannot be before Start Date.")

        self._handle_commitment_mode()

        if self.docstatus == 1:
            self.update_status(commit_to_db=False)

    def compute_end_date(self):
        if not self.start_date or not self.time_duration or not self.time_unit:
            return

        start = getdate(self.start_date)
        unit = self.time_unit.strip().lower()
        duration = int(self.time_duration)
        if unit == "day":
            end_exclusive = start + relativedelta(days=duration)
        elif unit == "week":
            end_exclusive = start + relativedelta(weeks=duration)
        elif unit == "month":
            end_exclusive = start + relativedelta(months=duration)
        elif unit == "year":
            end_exclusive = start + relativedelta(years=duration)
        else:
            return
        
        self.end_date = end_exclusive - relativedelta(days=1)


    def _handle_commitment_mode(self):
        ccpm = flt(self.comm_copies_pm) or 0
        crpc = flt(self.comm_rate_pc) or 0

        if self.copy_commitment:
            if ccpm > 0 and crpc > 0:
                self.comm_amt_pm = ccpm * crpc
            else:
                self.comm_amt_pm = 0.0
        elif self.amount_commitment:
            self.comm_copies_pm = 0
            self.comm_rate_pc = 0
        else:
            if ccpm > 0 and crpc > 0:
                self.comm_amt_pm = ccpm * crpc


    def on_submit(self):
        self.update_status()

    def on_cancel(self):
        self.db_set("status", "Cancelled", update_modified=False)

    def on_update_after_submit(self):
        self.update_status()

    def update_status(self, commit_to_db=True):
        new_status = "Active"
        if self.end_date and getdate(self.end_date) < getdate(today()):
            new_status = "Expired"

        if commit_to_db:
            self.db_set("status", new_status, update_modified=False)
        else:
            self.status = new_status


@frappe.whitelist()
def update_calculations(docname):
    doc = frappe.get_doc("Rent TG Agreement", docname)
    doc.compute_end_date()
    # doc._maybe_compute_committed_amount()
    doc._handle_commitment_mode()
    return {
        "end_date": doc.end_date,
        "comm_amt_pm": doc.comm_amt_pm
    }

def set_rent_tg_agreements_status():
    agreements = frappe.get_all(
        "Rent TG Agreement",
        filters={"docstatus": 1},
        fields=["name", "end_date", "status"],
    )

    for agr in agreements:
        if not agr.end_date:
            continue
        end = getdate(agr.end_date)
        if end < getdate(today()) and agr.status != "Expired":
            frappe.db.set_value("Rent TG Agreement", agr.name, "status", "Expired", update_modified=False)
        elif end >= getdate(today()) and agr.status != "Active":
            frappe.db.set_value("Rent TG Agreement", agr.name, "status", "Active", update_modified=False)


# create bill and populate available field from Rent TG AGR to TG & Rntal Bill
@frappe.whitelist()
def make_trb(source_name: str):
    """Create TG And Rental Bill from Rent TG Agreement"""
    rta = frappe.get_doc("Rent TG Agreement", source_name)
    if rta.status != "Active":
        frappe.throw("You can only create TG And Rental Bill from Active agreements.")

    trb = frappe.new_doc("TG And Rental Bill")
    trb.customer = rta.customer
    trb.agreement_no = rta.name
    trb.type = rta.agreement_type
    trb.cnt_start_dt = rta.start_date
    trb.cnt_end_dt = rta.end_date
    trb.comm_copies_pm = rta.comm_copies_pm
    trb.comm_rate_pc = rta.comm_rate_pc
    trb.comm_amt_pm = rta.comm_amt_pm
    trb.monthly_fix_amt = getattr(rta, "monthly_fix_amt", 0)

    for ait in rta.agreement_items:
        rit = trb.append("copies", {})
        rit.item = ait.item
        rit.rate = ait.rate
        rit.free_copies = ait.free_copies or 0
        rit.previous_cc = getattr(ait, "prev_cc", 0) or 0

    for tax in rta.taxes:
        trb.append("taxes", {
            "type": tax.type,
            "tax_rate": tax.tax_rate,
            "tax_amount": tax.tax_amount,
        })

    return trb


@frappe.whitelist()
def get_trb_defaults(agreement_no: str, posting_date: str | None = None):
    rta = frappe.get_doc("Rent TG Agreement", agreement_no)
    if rta.status != "Active":
        frappe.throw("Only Active agreements can be used.")

    return {
        "customer": rta.customer,
        "type": rta.agreement_type,
        "cnt_start_dt": rta.start_date,
        "cnt_end_dt": rta.end_date,
        "comm_copies_pm": rta.comm_copies_pm,
        "comm_rate_pc": rta.comm_rate_pc,
        "comm_amt_pm": rta.comm_amt_pm,
        "monthly_fix_amt": getattr(rta, "monthly_fix_amt", 0),
        "copies": [
            {
                "item": ait.item,
                "rate": ait.rate,
                "free_copies": ait.free_copies or 0,
                "previous_cc": ait.prev_cc or 0,   # ✅ directly from Agreement table
            }
            for ait in rta.agreement_items
        ],
        "taxes": [
            {
                "type": tax.type,
                "tax_rate": tax.tax_rate,
                "tax_amount": tax.tax_amount,
            }
            for tax in rta.taxes
        ]
    }