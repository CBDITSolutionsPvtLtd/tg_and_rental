frappe.listview_settings["Rent TG Agreement"] = {
    get_indicator: function (doc) {
        if (doc.status === "Active") {
            return [__("Active"), "green", "status,=,Active"];
        } else if (doc.status === "Expired") {
            return [__("Expired"), "red", "status,=,Expired"];
        } else if (doc.status === "Cancelled") {
            return [__("Cancelled"), "gray", "status,=,Cancelled"];
        } else {
            return [__("Draft"), "orange", "status,=,Draft"];
        }
    }
};
