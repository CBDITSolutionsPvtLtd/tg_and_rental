import frappe
import math
from frappe.utils import formatdate

def fmt(date_str):
    return formatdate(date_str, "dd-mm-yyyy") if date_str else None

@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_payment_entries(from_date: str = None, to_date: str = None):
    
    def parse_date(date_str):
        """Parse date from dd-mm-yyyy or yyyy-mm-dd format to yyyy-mm-dd"""
        if not date_str:
            return None
        
        from datetime import datetime
        
        try:
            date_obj = datetime.strptime(date_str, "%d-%m-%Y")
            return date_obj.strftime("%Y-%m-%d")
        except ValueError:
            pass
        
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            return date_obj.strftime("%Y-%m-%d")
        except ValueError:
            pass
        
        frappe.throw(f"Invalid date format: {date_str}. Expected dd-mm-yyyy or yyyy-mm-dd")
    
    # Convert dates to yyyy-mm-dd format
    from_date = parse_date(from_date)
    to_date = parse_date(to_date)
    
    filters = {
        "payment_type": "Receive",
        "docstatus": 1,
    }
    
    if from_date and to_date:
        filters["posting_date"] = ["between", [from_date, to_date]]
    elif from_date:
        filters["posting_date"] = [">=", from_date]
    elif to_date:
        filters["posting_date"] = ["<=", to_date]
    
    payments = frappe.get_list(
        "Payment Entry",
        filters=filters,
        fields=[
            "name",
            "posting_date",
            "mode_of_payment",
            "party",
            "reference_no",
            "reference_date",
            "remarks",
            "paid_amount",
        ],
        order_by="posting_date asc, name asc",
        ignore_permissions=True,
        as_list=False,
    )
    
    result = []
    
    for payment in payments:
        doc = frappe.get_doc("Payment Entry", payment.name)
        
        references = []
        for ref in doc.references or []:
            # Skip if not Sales Invoice
            if ref.reference_doctype != "Sales Invoice":
                continue
            
            ref_data = {
                "reference_doctype": ref.reference_doctype,
                "reference_name": ref.reference_name,
                "allocated_amount": ref.allocated_amount,
                "tg_rent_bill": None,  # Default value
            }
            
            if ref.reference_name:
                tg_rent_bill = frappe.db.get_value(
                    "Sales Invoice",
                    ref.reference_name,
                    "custom_tg_rent_bill"
                )
                ref_data["tg_rent_bill"] = tg_rent_bill
            
            references.append(ref_data)
        
        if references:
            entry = {
                "name": payment.name,
                "posting_date": fmt(payment.posting_date),
                "mode_of_payment": payment.mode_of_payment,
                "party": payment.party,
                "reference_no": payment.reference_no,
                "reference_date": fmt(payment.reference_date) if payment.reference_date else None,
                "remarks": payment.remarks,
                "paid_amount": payment.paid_amount,
                "references": references,
            }
            
            result.append(entry)
    
    return result
