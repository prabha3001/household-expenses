# -*- coding: utf-8 -*-
"""
Transaction categorisation logic — ported from the original household expense
analysis (categorize.py) into a pure, side-effect-free module so the web app
can classify a single freshly-parsed transaction at upload time, instead of
batch-processing a static JSON file.

All keyword lists, exclusion rules and category logic are unchanged from the
version that was validated against the user's real 12 months of statements.
"""
import re

MONTHS = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}

def parse_month(date_str):
    """'27 Jul 25' / '27 Jul 2025' -> '2025-07'"""
    m = re.search(r'(\d{2})\s*(\w{3})\s*(\d{2,4})', date_str or '')
    if not m:
        return None
    day, mon, yr = m.groups()
    mon = mon[:3].title()
    if mon not in MONTHS:
        return None
    yr = int(yr)
    if yr < 100:
        yr += 2000
    return f"{yr}-{MONTHS[mon]:02d}"

# Internal transfers between the household's own accounts. Excluded from both
# spend AND income totals to avoid double counting.
EXCLUDE_KEYWORDS_BANK_ONLY = [
    'ARUMUGAM', 'HSBC BNK VSA', 'BARCLAYCARD', '70016152',
]

ATM_TYPES_BY_ACCOUNT = {
    'HSBC Current Account': {'ATM'},
    'Halifax Current Account': {'CPT'},
}

DD_TYPES_BY_ACCOUNT = {
    'HSBC Current Account': {'DD'},
    'Halifax Current Account': {'DD'},
}

LOAN_KEYWORDS = [
    'HSBC PLC LOANS', 'CREATION.CO.UK', 'YOUR PLAN CARD PAY',
    'BARCLAYS PRTNR FIN', 'BARCLAYS PARTNER F',
    'HALIFAX',  # Halifax mortgage / housing-loan Direct Debit
]

BILL_PAYMENT_PATTERNS = [
    'PAYMENT - THANK YOU', 'DEBIT CARD PAYMENT RECEIVED', 'PAYMENT RECEIVED THANK YOU',
]

UTILITY_KEYWORDS = [
    'OCTOPUS ENERGY', 'UNITED UTILITIES', 'BRSK BROADBAND', 'TALKTALK',
    'YOUFIBRE', 'LYCAMOBILE', 'MANCHESTER C C', 'MANCHESTER CITY CO',
    'EE LIMITED', 'VODAFONE', ' O2 ', 'SKY DIGITAL', 'VIRGIN MEDIA',
    'THAMES WATER', 'BRITISH GAS', 'EDF ENERGY', 'SEVERN TRENT',
    'COUNCIL TAX', 'WWW.YOUFIBRE',
]

GROCERY_KEYWORDS = [
    'TESCO', 'ALDI', 'ASDA', 'SAINSBURY', 'MORRISON', 'LIDL', 'ICELAND',
    'CO-OP', 'COOPERATIVE', 'PPOINT_', 'NOOR CASH', 'MEGA MART',
    'APPNA CASH', 'COSTCO', 'NAFEES SWEET', 'FAIRMART', 'LNK TESCO',
    'LNK SALE CIRCLE', 'SPAR ', 'BUDGENS', 'NISA', 'CASH AND CARRY',
    'SANYA FOODS', 'WORLDWIDE FOODS', 'DESI S-MART', 'PARRYS SUPERMARKET',
    'OCEANFRESH', 'MANCHESTER SUPER', 'MANCHESTER FRESH',
]

HOTEL_FOOD_KEYWORDS = [
    'NANDOS', 'WING STOP', 'SUBWAY', 'GREGGS', 'COSTA COFFEE', 'MCDONALD',
    'CHI YIP', 'DERWENT CAFE', 'AZORIE CAFE', 'CHENNAI DOSA', 'BARBURRITO',
    'PRETTY THING', 'BUBBLEOLOG', 'HOUSE OF BIRYANI', 'PALAZZO MALABAR',
    'MANCHESTER PONGAL', 'SAI SPICE', 'MY THAI', 'CAKE BOX', 'KUMAR KITCHEN',
    'DADAR', 'KFC', 'DELIVEROO', 'JUST EAT', 'UBER EATS',
    'DOMINO', 'PIZZA', 'STARBUCKS', 'CAFFE NERO', 'COOKSMILL',
    'SHRI VENKATESWARA', 'LIVERPOOL GANESH', 'BROADHEATH SPICE',
    'TRAVELODGE', 'PREMIER INN', 'HOLIDAY INN', 'HOTEL', 'BOOKING.COM',
    'CHENS HAPPY HOUSE', 'SARAVANAA BHAVAN', 'POOJA SWEETS',
    'TURMERIC KITCHEN', 'CAMDEN FOOD', 'CHAIIWALA', 'KAIRALI', 'CLUCKSY',
    'SAYERS THE BAKERS', 'CREAMS CAFE', 'RANGEDESSE', 'GRILL FOOD',
    'LUGO ', 'FALAFEL', "SLIMMING W",
]

OTHER_SUBCATS = [
    ('Family Transfers & Remittances', [
        'REMITLY', 'TYAGI S', 'DR SIMONS ACADEMY', 'MATHEW THACHIL',
        'HOUSHANG MOHAMMADI', 'SAKTHIVADIVEL SOMA', 'ASWATHKUMAR GURUSA',
        'KOMADI JAYANTH', 'APPU JOSEPH', 'BINTO SIMON',
        'LATHA MOHANASUNDAR', 'MUHAMMAD ALI ASGHA', 'R. RAMSKUMAR',
        'DIVYA RENJITH', 'SASTIKA PRABAKAR', 'RICHARD COWELL',
        'MR TIMOTHY HERRICK', 'HARSHANYA PRABAKAR', 'ROSARY JOSEPH',
        'SHANMUGAM PACKIYAM', 'PUSHPARAJ MOHANRAJ', 'ALI JABBAREH',
        'AMALORPAVAMARY', 'JUDE KUMAR', 'VASU NARASIMMAN',
        'PRASATH RAMAMOORTH', 'XAVIER KURUSU', 'ELIZABETH ALAVANYO',
        'GURUSAMYRAJA', 'RINCY PAUL', 'S PRABAKAR', 'H PRABAKAR',
        'CHLOE SMITH', 'JONJO CROSBY', 'KRISHNA JETHVA', 'GFM INTERNATIONAL',
        'CLARE MILLMAN', 'SAMUEL BROOKS', 'MICHAEL INNES',
    ]),
    ('Insurance', ['HASTINGS INSURANCE', 'ASSURA DIV LIFE']),
    ('Transport, Parking & Travel', [
        'KERALA MOTORS', 'VFM AUTO', 'BRAYLEY NISSAN', 'HALFORDS', 'DVLA',
        'EURO CAR PARKS', 'METROLINK', 'SHELL ', 'GSF ', 'MH AUTOMOBILE',
        'TESCO PAY AT PUMP', 'LNK ROADCHEF', 'ALTRINCHAM STN',
        'RINGGO', 'WYTHENSHAWE CAR PA', 'STAMFORD QUARTER', 'NCP',
        'TFL TRAVEL', 'AVANTI WEST', 'FIRST WEST YORKSHI', 'BEE NETWORK',
        'WELCOME BREAK', 'HILTON PARK', 'ROADCHEF',
    ]),
    ('Cash Withdrawals', [
        'CASH HSBC', 'CASH POSTOFF', 'LNK NOTEMACHINE', 'CASH BNKM',
        'CASH RB SCOT', 'CASH NOTEMAC', 'CASH IN HSBC', 'LNK SHELL',
        'LNK MERCURY', 'HFX HFX', 'CASH HALIFAX',
    ]),
    ('Shopping & Retail', [
        'APPLE STORE', 'APPLE R136', 'AMAZON', 'TEMU', 'ARGOS',
        'SPORTSDIRECT', 'FGTL TA SPORTS', 'CLARKS', 'TK MAXX', 'PRIMARK',
        'THE RANGE', 'DUNELM', 'TRAVIS PERKINS', 'SELCO', 'WICKES', 'B&M',
        'HOME BARGAINS', 'PETITES MODES', 'SELFRIDGES', 'NYX',
        'SCREWFIX', 'EBAY', 'M&S', 'BRITISH HEART FOUNDATION',
        'HOBBYCRAFT', 'WATERSTONES', 'NEXT RETAIL', 'MAX SPIELMANN',
        'CITY ELECTRICAL', 'CARD FACTORY', 'EVRI', 'J D SPORTS',
        'TOOLSTATION', 'ARNDALE',
    ]),
    ('Education', [
        'MEDSCHOOLENTRY', 'PASSMYGCSE', 'SIGARA SCHOOL', 'PARENTPAY',
        'HAMBLIN EDUCATION', 'BIOLOGYDONERIGHT', 'MEDICMENTOR',
        'SIR JOHN DEANES', 'PSI SERVICES', 'VMS*SCOPAY', 'VUE*UKCAT',
    ]),
    ('Government, Admin & Fees', [
        'EXPERIAN', 'VFS-IVAC', 'DVLA DRIVERS', 'MANCHESTER CD',
        'MCC INTERNET', 'IHS1', 'UKVI', 'DISCLOSURE',
    ]),
    ('Health, Fitness & Personal Care', [
        'BROADHEATH PHARMACY', 'BOOTS', 'SUPERDRUG', 'LATE NIGHT PHARMACY',
        'DAVID LLOYD', 'ALTRINCHAM BARBERS',
    ]),
    ('Subscriptions & Tech', ['HPI INSTANT INK', 'AMAZON PRIME', 'BLUELIGHTCARD', 'GOOGLE *GOOGLE ONE']),
]

def classify(t):
    desc = t['desc'].upper()
    acc = t['account']

    if t.get('type') in ATM_TYPES_BY_ACCOUNT.get(acc, set()):
        return 'Other'

    if acc in ('HSBC Current Account', 'Halifax Current Account'):
        for kw in EXCLUDE_KEYWORDS_BANK_ONLY:
            if kw in desc:
                return 'Internal Transfer / CC Repayment (excluded)'

    for kw in LOAN_KEYWORDS:
        if kw in desc:
            return 'Loans'
    for kw in UTILITY_KEYWORDS:
        if kw in desc:
            return 'Utility Bills'
    for kw in GROCERY_KEYWORDS:
        if kw in desc:
            return 'Groceries'
    for kw in HOTEL_FOOD_KEYWORDS:
        if kw in desc:
            return 'Hotel/Food'
    return 'Other'

def other_subcat(t):
    acc = t['account']
    if t.get('type') in ATM_TYPES_BY_ACCOUNT.get(acc, set()):
        return 'Cash Withdrawals'
    d = t['desc'].upper()
    for name, kws in OTHER_SUBCATS:
        for kw in kws:
            if kw in d:
                return name
    return 'Miscellaneous'

SHOPPING_SUBCATS = [
    ('Amazon Prime (subscription)', ['AMAZON PRIME']),
    ('Amazon & Online Marketplace', ['AMAZON*', 'AMZNMKTPLACE', 'AMAZON.CO.UK*', 'EBAY', 'TEMU.COM']),
    ('Electronics & Tech', ['APPLE STORE', 'APPLE R136']),
    ('Home, DIY & Furniture', [
        'THE RANGE', 'DUNELM', 'SELCO TRADING', 'TRAVIS PERKINS', 'WICKES',
        'SCREWFIX', 'HOME BARGAINS', 'B&M 507', 'B&M 226', 'B&M -',
        'CITY ELECTRICAL', 'TOOLSTATION',
    ]),
    ('Clothing & Fashion', [
        'PETITES MODES', 'PRIMARK', 'CLARKS', 'TK MAXX', 'SPORTSDIRECT',
        'FGTL TA SPORTS', 'J D SPORTS', 'SELFRIDGES', 'NYX', 'M&S PLC',
    ]),
    ('Charity Shops', ['BRITISH HEART FOUNDATION']),
    ('General Retail', ['ARGOS', 'HOBBYCRAFT', 'WATERSTONES', 'NEXT RETAIL',
                         'MAX SPIELMANN', 'CARD FACTORY', 'EVRI', 'ARNDALE']),
]

def shopping_subcat(desc):
    d = desc.upper()
    for name, kws in SHOPPING_SUBCATS:
        for kw in kws:
            if kw in d:
                return name
    return 'Other Retail'

CANONICAL_MERCHANTS = [
    ('Tesco', ['TESCO']),
    ('Aldi', ['ALDI']),
    ('Amazon (incl. Marketplace & Prime)', ['AMAZON', 'AMZNMKTPLACE']),
    ('Sainsbury\'s', ['SAINSBURY']),
    ('Asda', ['ASDA']),
    ('Lidl', ['LIDL']),
    ('Costco', ['COSTCO']),
    ('Greggs', ['GREGGS']),
    ('Shell (fuel)', ['SHELL ']),
    ('B&M', ['B&M']),
    ('Mega Mart', ['MEGA MART']),
    ('ATM / Cash withdrawal', ['CASH HSBC', 'CASH POSTOFF', 'LNK NOTEMACHINE',
                                'CASH BNKM', 'CASH RB SCOT', 'CASH NOTEMAC',
                                'CASH IN HSBC', 'LNK SHELL', 'LNK MERCURY',
                                'HFX HFX', 'CASH HALIFAX', 'LNK TESCO',
                                'LNK SALE CIRCLE', 'LNK COOPERATIVE', 'LNK ROADCHEF']),
    ('L Mohanasundaram / Latha (family)', ['MOHANASUNDAR', 'LATHA']),
    ('Prabakar Arumugam (self-transfer)', ['ARUMUGAM', 'P ARUMUGAM']),
    ('Barclaycard payment', ['BARCLAYCARD']),
    ('Remitly (international transfer)', ['REMITLY']),
    ('Chi Yip / Chi Yip Altrincham', ['CHI YIP']),
    ('Fairmart', ['FAIRMART']),
    ('Chaiiwala', ['CHAIIWALA']),
    ('David Lloyd (gym)', ['DAVID LLOYD']),
    ('Halifax (mortgage / housing loan)', ['HALIFAX']),
]

def canonical_merchant(t):
    acc = t['account']
    if t.get('type') in ATM_TYPES_BY_ACCOUNT.get(acc, set()):
        return 'ATM / Cash withdrawal'
    desc = t['desc']
    d = desc.upper()
    for name, kws in CANONICAL_MERCHANTS:
        for kw in kws:
            if kw in d:
                return name
    return re.sub(r'\s+', ' ', desc).strip()


def categorize_transaction(t):
    """
    Take a raw parsed transaction dict (account, date, desc, amount, dir, type)
    and populate: month, is_dd, is_atm, canonical_merchant, category,
    subcategory, shopping_subcategory, is_refund — exactly matching the logic
    validated against the user's original 12 months of statements.
    Mutates and returns t.
    """
    t.setdefault('month', None)
    if not t.get('month'):
        t['month'] = parse_month(t['date'])
    t['is_dd'] = t['account'] in DD_TYPES_BY_ACCOUNT and t.get('type') in DD_TYPES_BY_ACCOUNT.get(t['account'], set())
    t['is_atm'] = t['account'] in ATM_TYPES_BY_ACCOUNT and t.get('type') in ATM_TYPES_BY_ACCOUNT.get(t['account'], set())
    t['canonical_merchant'] = canonical_merchant(t)
    if t['dir'] == 'out':
        t['category'] = classify(t)
        t['subcategory'] = other_subcat(t) if t['category'] == 'Other' else ''
        t['shopping_subcategory'] = shopping_subcat(t['desc']) if t['subcategory'] == 'Shopping & Retail' else ''
        t['is_refund'] = False
    else:
        desc = t['desc'].upper()
        if t['account'] in ('HSBC Current Account', 'Halifax Current Account') and \
           any(kw in desc for kw in EXCLUDE_KEYWORDS_BANK_ONLY):
            t['category'] = 'Internal Transfer / CC Repayment (excluded)'
        elif t['account'] in ('HSBC Credit Card', 'Barclaycard'):
            if any(p in desc for p in BILL_PAYMENT_PATTERNS):
                t['category'] = 'Internal Transfer / CC Repayment (excluded)'
            else:
                t['is_refund'] = True
                t['category'] = classify(t)
                t['subcategory'] = other_subcat(t) if t['category'] == 'Other' else ''
                t['shopping_subcategory'] = shopping_subcat(t['desc']) if t['subcategory'] == 'Shopping & Retail' else ''
        else:
            t['category'] = 'Income'
        t.setdefault('subcategory', '')
        t.setdefault('shopping_subcategory', '')
        t.setdefault('is_refund', False)
    return t
