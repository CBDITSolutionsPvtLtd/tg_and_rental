import frappe
import math
from frappe.utils import formatdate


def fmt(date_str):
    return formatdate(date_str, "dd-mm-yyyy") if date_str else None


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_tg_rental_bills(month: str = None, year: int = None):
    if not month or not year:
        frappe.throw("month and year are required")

    bills = frappe.get_list(
        "TG And Rental Bill",
        filters={
            "month": month,
            "year": year,
            "docstatus": 1,
        },
        fields=[
            "name",
            "type",
            "customer",
            "agreement_no",
            "posting_date",
            "due_date",
            "bill_from",
            "bill_to",
            "grand_total",
            "status",
            "cnt_start_dt",
            "cnt_end_dt",
            "monthly_fix_amt",
            "comm_amt_pm",
            "total_amt",
        ],
        order_by="posting_date asc, name asc",
        ignore_permissions=True,
        as_list=False,
    )

    result = []

    for b in bills:
        doc = frappe.get_doc("TG And Rental Bill", b.name)
        agrmt = frappe.get_doc("Rent TG Agreement", doc.agreement_no)
        custmr = frappe.get_doc("Customer", doc.customer)

        grand_total = math.floor(doc.grand_total * 100) / 100
        round_grand_total = round(grand_total)
        round_off = round(round_grand_total - grand_total, 2)

        total_amt = doc.total_amt or 0
        monthly_fix_amt = doc.monthly_fix_amt or 0
        comm_amt_pm = doc.comm_amt_pm or 0

        copies = []

        # Flattened fields for Monthly Commitment Amount (MCA) or Monthly Fixed Amount (MFA)
        MCA = None
        MFA = None

        # Condition 1: monthly_fix_amt == 0 and comm_amt_pm > 0 and total_amt < comm_amt_pm
        if monthly_fix_amt == 0 and comm_amt_pm > 0 and total_amt < comm_amt_pm:
            # Set all existing copies net_copy to 0
            for row in doc.copies or []:
                copies.append({
                    "item": row.item,
                    "current_cc": row.current_cc,
                    "previous_cc": row.previous_cc,
                    "free_copies": row.free_copies,
                    "net_copy": 0,
                    "rate": row.rate,
                    "amount": row.amount,
                    "uom": "Nos",
                })
            MCA = comm_amt_pm

        # Condition 2: monthly_fix_amt > 0 and comm_amt_pm == 0 and total_amt < 0
        elif monthly_fix_amt > 0 and comm_amt_pm == 0 and total_amt < 0:
            # Set all existing copies net_copy to 0
            for row in doc.copies or []:
                copies.append({
                    "item": row.item,
                    "current_cc": row.current_cc,
                    "previous_cc": row.previous_cc,
                    "free_copies": row.free_copies,
                    "net_copy": 0,
                    "rate": row.rate,
                    "amount": row.amount,
                    "uom": "Nos",
                })
            MFA = monthly_fix_amt

        # Condition 3: monthly_fix_amt > 0 and comm_amt_pm == 0 and total_amt > 0
        elif monthly_fix_amt > 0 and comm_amt_pm == 0 and total_amt > 0:
            for row in doc.copies or []:
                copies.append({
                    "item": row.item,
                    "current_cc": row.current_cc,
                    "previous_cc": row.previous_cc,
                    "free_copies": row.free_copies,
                    "net_copy": row.net_copy,
                    "rate": row.rate,
                    "amount": row.amount,
                    "uom": "Nos",
                })
            MFA = monthly_fix_amt

        else:
            for row in doc.copies or []:
                copies.append({
                    "item": row.item,
                    "current_cc": row.current_cc,
                    "previous_cc": row.previous_cc,
                    "free_copies": row.free_copies,
                    "net_copy": row.net_copy,
                    "rate": row.rate,
                    "amount": row.amount,
                    "uom": "Nos",
                })

        taxes = {}
        for tax in doc.taxes or []:
            taxes[tax.type] = round(tax.tax_amount, 2)

        entry = {
            "id": doc.name,
            "type": doc.type,
            "agreement_no": doc.agreement_no,
            "status": doc.status,
            "posting_date": fmt(doc.posting_date),
            "due_date": fmt(doc.due_date),
            "bill_from": fmt(doc.bill_from),
            "bill_to": fmt(doc.bill_to),
            "contract_from": fmt(doc.cnt_start_dt),
            "contract_to": fmt(doc.cnt_end_dt),
            "monthly_fix_amt": monthly_fix_amt,
            "monthly_cmt_amt": comm_amt_pm,
            "actual_total": doc.actual_total,

            "grand_total": grand_total,
            "round_grand_total": round_grand_total,
            "round_off": round_off,

            "customer": doc.customer,
            "model_no": agrmt.model_no,
            "serial_no": agrmt.serial_no,
            "add1": agrmt.address_line1,
            "add2": agrmt.address_line2,
            "city": agrmt.city,
            "state": agrmt.state,
            "pincode": agrmt.pincode,
            "gst_no": agrmt.gst_no,
            "pan": custmr.pan,
            "registration_type": custmr.gst_category,
            "copies": copies,
        }

        # Add flattened MCA or MFA if set
        if MCA is not None:
            entry["MCA"] = MCA
        if MFA is not None:
            entry["MFA"] = MFA

        entry.update(taxes)

        result.append(entry)

    return result
