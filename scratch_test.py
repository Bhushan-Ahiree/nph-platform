import re

def clean_phone_norm(value):
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 10:
        return digits
    return digits if digits else None

def impl_2(broker_phone):
    clean_phone_for_source = re.sub(r"\D", "", str(broker_phone)) if broker_phone else None
    if clean_phone_for_source and len(clean_phone_for_source) == 12 and clean_phone_for_source.startswith("91"):
        clean_phone_for_source = clean_phone_for_source[2:]
    return clean_phone_for_source

def impl_3(broker_phone):
    clean_phone = re.sub(r"\D", "", str(broker_phone))
    if len(clean_phone) == 12 and clean_phone.startswith("91"):
        clean_phone = clean_phone[2:]
    return clean_phone

def impl_4(broker_phone):
    clean_phone = None
    if broker_phone:
        clean_phone = re.sub(r"\D", "", str(broker_phone))
        if len(clean_phone) == 12 and clean_phone.startswith("91"):
            clean_phone = clean_phone[2:]
        if len(clean_phone) != 10:
            clean_phone = clean_phone if clean_phone else None
    return clean_phone

test_cases = [
    "+91 9876543210",
    "91 9876543210",
    "09876543210",
    "98765 43210",
    "call broker 9876543210 please",
    "invalid",
    None,
    ""
]

print(f"{'Input':<30} | {'norm':<15} | {'impl_2':<15} | {'impl_3':<15} | {'impl_4':<15}")
print("-" * 100)
for tc in test_cases:
    n = repr(clean_phone_norm(tc))
    i2 = repr(impl_2(tc))
    i3 = repr(impl_3(tc))
    i4 = repr(impl_4(tc))
    print(f"{repr(tc):<30} | {n:<15} | {i2:<15} | {i3:<15} | {i4:<15}")
