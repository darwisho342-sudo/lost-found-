"""Stable, reusable choices for structured item reports."""

from django.utils.translation import gettext_lazy as _


CATEGORY_CHOICES = (
    ("electronics", _("Electronics")), ("bags", _("Bags")),
    ("clothing", _("Clothing")), ("documents", _("Documents")),
    ("keys", _("Keys")), ("wallets", _("Wallets and Purses")),
    ("jewellery", _("Jewellery")), ("books", _("Books and Stationery")),
    ("sports_equipment", _("Sports Equipment")),
    ("personal_accessories", _("Personal Accessories")),
    ("other", _("Other")), ("not_sure", _("Not Sure")),
)

ITEM_TYPE_CHOICES = {
    "electronics": (("mobile_phone", _("Mobile Phone")), ("laptop", _("Laptop")),
        ("tablet", _("Tablet")), ("smartwatch", _("Smartwatch")),
        ("earbuds", _("Earbuds")), ("headphones", _("Headphones")),
        ("charger", _("Charger")), ("cable", _("Cable")),
        ("power_bank", _("Power Bank")), ("camera", _("Camera")),
        ("calculator", _("Calculator")), ("usb_drive", _("USB Drive"))),
    "bags": (("backpack", _("Backpack")), ("handbag", _("Handbag")),
        ("laptop_bag", _("Laptop Bag")), ("school_bag", _("School Bag")),
        ("sports_bag", _("Sports Bag")), ("suitcase", _("Suitcase")),
        ("shopping_bag", _("Shopping Bag"))),
    "clothing": (("jacket", _("Jacket")), ("coat", _("Coat")),
        ("shirt", _("Shirt")), ("t_shirt", _("T-Shirt")),
        ("trousers", _("Trousers")), ("dress", _("Dress")),
        ("shoes", _("Shoes")), ("hat", _("Hat")), ("scarf", _("Scarf")),
        ("gloves", _("Gloves"))),
    "documents": (("student_id", _("Student ID Card")), ("bank_card", _("Bank Card")),
        ("transport_card", _("Transportation Card")), ("driver_licence", _("Driver's Licence")),
        ("national_id", _("National ID Card")), ("passport", _("Passport")),
        ("certificate", _("Certificate")), ("notebook", _("Notebook"))),
    "keys": (("house_keys", _("House Keys")), ("car_keys", _("Car Keys")),
        ("office_keys", _("Office Keys")), ("locker_key", _("Locker Key")),
        ("keychain", _("Keychain")), ("electronic_key", _("Electronic Key"))),
    "wallets": (("wallet", _("Wallet")), ("purse", _("Purse")),
        ("card_holder", _("Card Holder")), ("coin_purse", _("Coin Purse"))),
    "jewellery": (("ring", _("Ring")), ("necklace", _("Necklace")),
        ("bracelet", _("Bracelet")), ("earrings", _("Earrings")), ("watch", _("Watch"))),
    "books": (("textbook", _("Textbook")), ("notebook", _("Notebook")),
        ("folder", _("Folder")), ("pencil_case", _("Pencil Case")),
        ("pen", _("Pen")), ("calculator", _("Calculator"))),
    "sports_equipment": (("sports_bag", _("Sports Bag")), ("ball", _("Ball")),
        ("racket", _("Racket")), ("sports_clothing", _("Sports Clothing")),
        ("water_bottle", _("Water Bottle"))),
    "personal_accessories": (("glasses", _("Glasses")), ("sunglasses", _("Sunglasses")),
        ("umbrella", _("Umbrella")), ("water_bottle", _("Water Bottle")),
        ("watch", _("Watch")), ("head_covering", _("Head Covering"))),
    "other": (), "not_sure": (),
}
for _category in ITEM_TYPE_CHOICES:
    ITEM_TYPE_CHOICES[_category] = (*ITEM_TYPE_CHOICES[_category], ("other", _("Other")), ("not_sure", _("Not Sure")))

ALL_ITEM_TYPE_CHOICES = tuple(dict.fromkeys(
    choice for choices in ITEM_TYPE_CHOICES.values() for choice in choices
))

COLOUR_CHOICES = tuple((value, label) for value, label in (
    ("black", _("Black")), ("white", _("White")), ("grey", _("Grey")),
    ("silver", _("Silver")), ("red", _("Red")), ("blue", _("Blue")),
    ("dark_blue", _("Dark Blue")), ("green", _("Green")), ("yellow", _("Yellow")),
    ("orange", _("Orange")), ("purple", _("Purple")), ("pink", _("Pink")),
    ("brown", _("Brown")), ("beige", _("Beige")), ("gold", _("Gold")),
    ("multicoloured", _("Multicoloured")), ("transparent", _("Transparent")),
    ("other", _("Other")), ("not_sure", _("Not Sure")),
))

MATERIAL_CHOICES = (("plastic", _("Plastic")), ("metal", _("Metal")),
    ("leather", _("Leather")), ("fabric", _("Fabric")), ("glass", _("Glass")),
    ("paper", _("Paper")), ("wood", _("Wood")), ("rubber", _("Rubber")),
    ("mixed", _("Mixed Materials")), ("other", _("Other")), ("not_sure", _("Not Sure")))
SIZE_CHOICES = (("xs", _("Extra Small")), ("small", _("Small")),
    ("medium", _("Medium")), ("large", _("Large")), ("xl", _("Extra Large")),
    ("not_sure", _("Not Sure")))
PATTERN_CHOICES = (("plain", _("Plain")), ("striped", _("Striped")),
    ("checked", _("Checked")), ("printed", _("Printed")), ("floral", _("Floral")),
    ("logo", _("Logo")), ("multicoloured", _("Multicoloured")),
    ("other", _("Other")), ("not_sure", _("Not Sure")))
CONDITION_CHOICES = (("new", _("New")), ("good", _("Good")),
    ("used", _("Used")), ("damaged", _("Damaged")), ("not_sure", _("Not Sure")))

BRAND_CHOICES = (("apple", "Apple"), ("samsung", "Samsung"), ("huawei", "Huawei"),
    ("xiaomi", "Xiaomi"), ("lenovo", "Lenovo"), ("hp", "HP"), ("dell", "Dell"),
    ("asus", "ASUS"), ("sony", "Sony"), ("adidas", "Adidas"), ("nike", "Nike"),
    ("puma", "Puma"), ("no_visible_brand", _("No Visible Brand")),
    ("other", _("Other")), ("not_sure", _("Not Sure")))

LOCATION_CHOICES = (("main_entrance", _("Main Entrance")), ("library", _("Library")),
    ("cafeteria", _("Cafeteria")), ("classroom", _("Classroom Building")),
    ("laboratory", _("Laboratory")), ("student_affairs", _("Student Affairs")),
    ("administration", _("Administration Building")), ("conference_hall", _("Conference Hall")),
    ("sports_area", _("Sports Area")), ("university_garden", _("University Garden")),
    ("parking", _("Parking Area")), ("bus_stop", _("Shuttle or Bus Stop")),
    ("restroom", _("Restroom")), ("prayer_area", _("Prayer Area")),
    ("other", _("Other")), ("not_sure", _("Not Sure")))

PLACE_TYPE_CHOICES = (
    ("university_school", _("University or school")),
    ("airport", _("Airport")),
    ("public_transport", _("Public transport")),
    ("shopping_centre", _("Shopping centre")),
    ("shop", _("Shop")),
    ("restaurant_cafe", _("Restaurant or cafe")),
    ("hotel", _("Hotel")),
    ("office_workplace", _("Office or workplace")),
    ("hospital_clinic", _("Hospital or clinic")),
    ("police_security", _("Police or security office")),
    ("street_public", _("Street or public area")),
    ("park_recreation", _("Park or recreation area")),
    ("sports_facility", _("Sports facility")),
    ("residential", _("Residential area")),
    ("event_venue", _("Event venue")),
    ("other", _("Other")),
    ("not_sure", _("Not Sure")),
)

# A deliberately bundled, local list. Stable ISO-style codes are stored while
# translated labels are rendered by Django; no runtime country service is used.
COUNTRY_CHOICES = (
    ("TR", _("Türkiye")), ("CY", _("Cyprus")), ("GB", _("United Kingdom")),
    ("US", _("United States")), ("CA", _("Canada")), ("DE", _("Germany")),
    ("FR", _("France")), ("IT", _("Italy")), ("ES", _("Spain")),
    ("NL", _("Netherlands")), ("BE", _("Belgium")), ("GR", _("Greece")),
    ("AU", _("Australia")), ("NZ", _("New Zealand")),
    ("AE", _("United Arab Emirates")), ("SA", _("Saudi Arabia")),
    ("EG", _("Egypt")), ("JO", _("Jordan")), ("LB", _("Lebanon")),
    ("IQ", _("Iraq")), ("QA", _("Qatar")), ("KW", _("Kuwait")),
    ("MA", _("Morocco")), ("TN", _("Tunisia")), ("DZ", _("Algeria")),
    ("IN", _("India")), ("PK", _("Pakistan")), ("BD", _("Bangladesh")),
    ("JP", _("Japan")), ("KR", _("South Korea")), ("CN", _("China")),
    ("BR", _("Brazil")), ("MX", _("Mexico")), ("AR", _("Argentina")),
    ("ZA", _("South Africa")), ("NG", _("Nigeria")), ("KE", _("Kenya")),
    ("OTHER", _("Other country")),
)

RETURN_METHOD_CHOICES = (
    ("security", _("University Lost and Found office")),
    ("trusted_organization", _("Authorized public authority")),
    ("safe_public_meeting", _("In-person meeting in a safe public place")),
    ("local_authority", _("Trusted local authority or organization")),
    ("private_shipping", _("Privately arranged shipping (FindMatch does not provide shipping)")),
)

RETURN_STATUS_CHOICES = (
    ("arranging", _("Arranging Return")),
    ("ready_pickup", _("Ready for Pickup")),
    ("handed_over", _("Handed Over")),
    ("awaiting_receipt", _("Awaiting Receipt Confirmation")),
    ("received", _("Received")),
    ("disputed", _("Disputed")),
)

VERIFICATION_QUESTION_TYPES = (("hidden_mark", _("Describe a hidden mark.")),
    ("contents", _("What was inside the item?")), ("exact_location", _("Where exactly was it lost?")),
    ("lock_screen", _("What does the lock screen look like?")),
    ("accessory", _("Describe a unique accessory.")), ("serial_part", _("Provide part of the serial number.")),
    ("engraving", _("Describe an engraving.")), ("other", _("Other private verification question")))
