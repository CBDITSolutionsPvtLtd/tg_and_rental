frappe.listview_settings["TG And Rental Bill"] = {
    get_indicator: function (doc) {
        if (doc.status === "Billed (Not Invoiced)") {
            return [__("Billed (Not Invoiced)"), "blue", "status,=,Billed (Not Invoiced)"];
        } else if (doc.status === "Overdue (Not Invoiced)") {
            return [__("Overdue (Not Invoiced)"), "red", "status,=,Overdue (Not Invoiced)"];
        } else if (doc.status === "Unpaid") {
            return [__("Unpaid"), "orange", "status,=,Unpaid"];
        } else if (doc.status === "Overdue") {
            return [__("Overdue"), "red", "status,=,Overdue"];
        } else if (doc.status === "Partly Paid") {
            return [__("Partly Paid"), "yellow", "status,=,Partly Paid"];
        } else if (doc.status === "Paid") {
            return [__("Paid"), "green", "status,=,Paid"];
        } else if (doc.status === "Cancelled") {
            return [__("Cancelled"), "black", "status,=,Cancelled"];
        } else if (doc.status === "Draft") {
            return [__("Draft"), "purple", "status,=,Draft"];
        } else {
            return [__(doc.status || "Unknown"), "gray", "status,=," + doc.status];
        }
    }
};
