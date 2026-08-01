package contextiq.authz

default allow := false

engineer_roles := {"admin", "platform_engineer", "developer", "manager"}

classification := lower(input.classification_label)

allow if {
    classification == "public"
}

allow if {
    classification == "internal"
    some role in input.user_roles
    role in engineer_roles
}

allow if {
    classification in {"confidential", "restricted"}
    some role in input.user_roles
    role == "admin"
}

deny_reason := msg if {
    not allow
    msg := sprintf("Access denied for classification '%v' and roles %v", [input.classification_label, input.user_roles])
}
