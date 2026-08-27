# Copyright (c) 2025, Mack and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class RentedItemsTable(Document):
    def validate(self):
        if self.current_cc is not None and self.previous_cc is not None:
            if self.current_cc < self.previous_cc:
                frappe.throw(
                    f"Current CC ({self.current_cc}) cannot be less than Previous CC ({self.previous_cc}) "
                    f"for item {self.item}"
                )
