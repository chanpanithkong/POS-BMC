/**
 * Illustrative retail catalogue for the demo. Prices, costs and rates are
 * placeholders, not real or confirmed data (SRS "Illustrative" category).
 */
export interface SeedCategory {
  code: string;
  nameEn: string;
  nameKm: string;
  icon: string;
  returnable?: boolean;
  returnWindowDays?: number;
  expiry?: boolean;
  minMarginPct?: number;
  taxExempt?: boolean;
}

export const CATEGORIES: SeedCategory[] = [
  { code: "BEV", nameEn: "Beverages", nameKm: "ភេសជ្ជៈ", icon: "cup-soda", minMarginPct: 10 },
  { code: "SNK", nameEn: "Snacks", nameKm: "អាហារសម្រន់", icon: "cookie", minMarginPct: 12 },
  { code: "GRC", nameEn: "Grocery", nameKm: "គ្រឿងទេស", icon: "shopping-basket", minMarginPct: 8 },
  { code: "DRY", nameEn: "Dairy and Chilled", nameKm: "ទឹកដោះគោ", icon: "milk", expiry: true, returnable: false, minMarginPct: 10 },
  { code: "FRU", nameEn: "Fresh Produce", nameKm: "បន្លែផ្លែឈើ", icon: "apple", returnable: false, taxExempt: true, minMarginPct: 15 },
  { code: "HOM", nameEn: "Household", nameKm: "សម្ភារៈផ្ទះ", icon: "spray-can", returnWindowDays: 14, minMarginPct: 15 },
  { code: "PCR", nameEn: "Personal Care", nameKm: "ថែរក្សាខ្លួន", icon: "sparkles", returnWindowDays: 14, minMarginPct: 18 },
  { code: "APP", nameEn: "Apparel", nameKm: "សម្លៀកបំពាក់", icon: "shirt", returnWindowDays: 30, minMarginPct: 25 },
  { code: "SRV", nameEn: "Services", nameKm: "សេវាកម្ម", icon: "gift", returnable: false, minMarginPct: 0 },
];

export const BRANDS = ["Vital", "Kulen Springs", "Angkor Foods", "Mekong Roast", "Lotus Home", "SilkSoft", "Tonle Dairy", "Nimmit", "Sabay Snacks", "Riel Wear"];

export interface SeedProduct {
  sku: string;
  nameEn: string;
  nameKm: string;
  category: string;
  brand: string | null;
  unit: "BTL" | "CAN" | "PCS" | "PKT" | "BOX" | "KG" | "SVC";
  price: number;
  cost: number;
  wholesale?: number;
  barcode?: string;
  carton?: { unit: "CTN" | "PACK"; factor: number; barcode?: string };
  reorder: number;
  max: number;
  stock: number;
  favourite?: boolean;
  weighed?: boolean;
  service?: boolean;
  expiry?: boolean;
  minPrice?: number;
}

export const PRODUCTS: SeedProduct[] = [
  { sku: "BEV-1001", nameEn: "Drinking Water 500 ml", nameKm: "ទឹកសុទ្ធ ៥០០ មល", category: "BEV", brand: "Vital", unit: "BTL", price: 0.5, cost: 0.22, wholesale: 0.4, carton: { unit: "CTN", factor: 24 }, reorder: 60, max: 480, stock: 260, favourite: true },
  { sku: "BEV-1002", nameEn: "Drinking Water 1.5 L", nameKm: "ទឹកសុទ្ធ ១.៥ លីត្រ", category: "BEV", brand: "Vital", unit: "BTL", price: 0.8, cost: 0.38, wholesale: 0.65, carton: { unit: "CTN", factor: 12 }, reorder: 40, max: 240, stock: 130, favourite: true },
  { sku: "BEV-1003", nameEn: "Mineral Water 600 ml", nameKm: "ទឹករ៉ែ ៦០០ មល", category: "BEV", brand: "Kulen Springs", unit: "BTL", price: 0.6, cost: 0.28, carton: { unit: "CTN", factor: 24 }, reorder: 48, max: 360, stock: 150 },
  { sku: "BEV-1004", nameEn: "Cola 330 ml Can", nameKm: "កូឡា ៣៣០ មល", category: "BEV", brand: "Nimmit", unit: "CAN", price: 0.75, cost: 0.42, wholesale: 0.62, carton: { unit: "CTN", factor: 24 }, reorder: 48, max: 360, stock: 210, favourite: true },
  { sku: "BEV-1005", nameEn: "Lemon Soda 330 ml Can", nameKm: "សូដាក្រូចឆ្មារ ៣៣០ មល", category: "BEV", brand: "Nimmit", unit: "CAN", price: 0.75, cost: 0.41, carton: { unit: "CTN", factor: 24 }, reorder: 36, max: 288, stock: 34 },
  { sku: "BEV-1006", nameEn: "Iced Coffee 240 ml Can", nameKm: "កាហ្វេទឹកកក ២៤០ មល", category: "BEV", brand: "Mekong Roast", unit: "CAN", price: 1.1, cost: 0.62, carton: { unit: "CTN", factor: 24 }, reorder: 24, max: 192, stock: 96, favourite: true },
  { sku: "BEV-1007", nameEn: "Coffee 3-in-1 Box (20 sachets)", nameKm: "កាហ្វេ ៣ក្នុង១ (២០កញ្ចប់)", category: "BEV", brand: "Mekong Roast", unit: "BOX", price: 2.0, cost: 1.25, wholesale: 1.75, carton: { unit: "CTN", factor: 12 }, reorder: 15, max: 90, stock: 62, favourite: true },
  { sku: "BEV-1008", nameEn: "Jasmine Green Tea 500 ml", nameKm: "តែបៃតងម្លិះ ៥០០ មល", category: "BEV", brand: "Kulen Springs", unit: "BTL", price: 0.9, cost: 0.5, carton: { unit: "CTN", factor: 24 }, reorder: 24, max: 192, stock: 0 },
  { sku: "BEV-1009", nameEn: "Energy Drink 250 ml", nameKm: "ភេសជ្ជៈថាមពល ២៥០ មល", category: "BEV", brand: "Nimmit", unit: "CAN", price: 0.85, cost: 0.47, carton: { unit: "CTN", factor: 24 }, reorder: 36, max: 288, stock: 180 },
  { sku: "SNK-2001", nameEn: "Potato Chips Original 75 g", nameKm: "ដំឡូងបារាំងចៀន ៧៥ក្រាម", category: "SNK", brand: "Sabay Snacks", unit: "PKT", price: 1.0, cost: 0.58, wholesale: 0.85, carton: { unit: "CTN", factor: 36 }, reorder: 30, max: 216, stock: 118, favourite: true },
  { sku: "SNK-2002", nameEn: "Shrimp Crackers 60 g", nameKm: "នំបង្គា ៦០ក្រាម", category: "SNK", brand: "Sabay Snacks", unit: "PKT", price: 0.7, cost: 0.38, carton: { unit: "CTN", factor: 36 }, reorder: 30, max: 216, stock: 21 },
  { sku: "SNK-2003", nameEn: "Roasted Cashews 150 g", nameKm: "គ្រាប់ស្វាយចន្ទីលីង ១៥០ក្រាម", category: "SNK", brand: "Angkor Foods", unit: "PKT", price: 3.5, cost: 2.3, reorder: 12, max: 72, stock: 44 },
  { sku: "SNK-2004", nameEn: "Chocolate Wafer 45 g", nameKm: "នំវ៉ាហ្វើសូកូឡា ៤៥ក្រាម", category: "SNK", brand: "Sabay Snacks", unit: "PCS", price: 0.55, cost: 0.3, carton: { unit: "CTN", factor: 48 }, reorder: 40, max: 288, stock: 165 },
  { sku: "SNK-2005", nameEn: "Dried Mango 100 g", nameKm: "ស្វាយក្រៀម ១០០ក្រាម", category: "SNK", brand: "Angkor Foods", unit: "PKT", price: 2.4, cost: 1.45, reorder: 15, max: 90, stock: 58 },
  { sku: "GRC-3001", nameEn: "Jasmine Rice 5 kg", nameKm: "អង្ករផ្កាម្លិះ ៥គីឡូ", category: "GRC", brand: "Angkor Foods", unit: "PCS", price: 7.5, cost: 5.6, wholesale: 6.8, reorder: 12, max: 80, stock: 45, favourite: true },
  { sku: "GRC-3002", nameEn: "Fish Sauce 700 ml", nameKm: "ទឹកត្រី ៧០០ មល", category: "GRC", brand: "Angkor Foods", unit: "BTL", price: 1.8, cost: 1.15, carton: { unit: "CTN", factor: 12 }, reorder: 18, max: 120, stock: 77 },
  { sku: "GRC-3003", nameEn: "Soy Sauce 500 ml", nameKm: "ទឹកស៊ីអ៊ីវ ៥០០ មល", category: "GRC", brand: "Angkor Foods", unit: "BTL", price: 1.5, cost: 0.95, carton: { unit: "CTN", factor: 12 }, reorder: 18, max: 120, stock: 66 },
  { sku: "GRC-3004", nameEn: "Palm Sugar 500 g", nameKm: "ស្ករត្នោត ៥០០ក្រាម", category: "GRC", brand: "Angkor Foods", unit: "PKT", price: 1.6, cost: 1.0, reorder: 15, max: 90, stock: 12 },
  { sku: "GRC-3005", nameEn: "Instant Noodles Chicken 70 g", nameKm: "មីកញ្ចប់រសមាន់ ៧០ក្រាម", category: "GRC", brand: "Sabay Snacks", unit: "PKT", price: 0.35, cost: 0.2, wholesale: 0.29, carton: { unit: "CTN", factor: 30 }, reorder: 60, max: 480, stock: 300, favourite: true },
  { sku: "GRC-3006", nameEn: "Cooking Oil 1 L", nameKm: "ប្រេងឆា ១លីត្រ", category: "GRC", brand: "Angkor Foods", unit: "BTL", price: 2.6, cost: 1.95, carton: { unit: "CTN", factor: 12 }, reorder: 18, max: 120, stock: 72 },
  { sku: "DRY-4001", nameEn: "Fresh Milk 1 L", nameKm: "ទឹកដោះគោស្រស់ ១លីត្រ", category: "DRY", brand: "Tonle Dairy", unit: "BTL", price: 2.2, cost: 1.55, reorder: 18, max: 96, stock: 42, favourite: true, expiry: true },
  { sku: "DRY-4002", nameEn: "Plain Yogurt 135 g", nameKm: "យ៉ាអួ ១៣៥ក្រាម", category: "DRY", brand: "Tonle Dairy", unit: "PCS", price: 0.65, cost: 0.4, reorder: 24, max: 144, stock: 70, expiry: true },
  { sku: "DRY-4003", nameEn: "Butter 200 g", nameKm: "ប៊ឺ ២០០ក្រាម", category: "DRY", brand: "Tonle Dairy", unit: "PCS", price: 3.2, cost: 2.3, reorder: 8, max: 48, stock: 22, expiry: true },
  { sku: "FRU-5001", nameEn: "Banana", nameKm: "ចេក", category: "FRU", brand: null, unit: "KG", price: 1.2, cost: 0.7, reorder: 8, max: 60, stock: 28, weighed: true, favourite: true },
  { sku: "FRU-5002", nameEn: "Mango Keo Romeat", nameKm: "ស្វាយកែវរមៀត", category: "FRU", brand: null, unit: "KG", price: 1.9, cost: 1.15, reorder: 8, max: 50, stock: 19.5, weighed: true },
  { sku: "FRU-5003", nameEn: "Morning Glory", nameKm: "ត្រកួន", category: "FRU", brand: null, unit: "KG", price: 1.0, cost: 0.55, reorder: 6, max: 30, stock: 11.25, weighed: true },
  { sku: "HOM-6001", nameEn: "Dish Soap 800 ml", nameKm: "សាប៊ូលាងចាន ៨០០ មល", category: "HOM", brand: "Lotus Home", unit: "BTL", price: 2.4, cost: 1.5, carton: { unit: "CTN", factor: 12 }, reorder: 12, max: 72, stock: 40 },
  { sku: "HOM-6002", nameEn: "Laundry Powder 3 kg", nameKm: "ម្សៅបោកខោអាវ ៣គីឡូ", category: "HOM", brand: "Lotus Home", unit: "PCS", price: 6.9, cost: 4.8, reorder: 8, max: 48, stock: 26 },
  { sku: "HOM-6003", nameEn: "Toilet Tissue 10 Rolls", nameKm: "ក្រដាសអនាម័យ ១០មូរ", category: "HOM", brand: "Lotus Home", unit: "PKT", price: 3.3, cost: 2.2, reorder: 12, max: 72, stock: 95 },
  { sku: "HOM-6004", nameEn: "Trash Bags Large 30 pcs", nameKm: "ថង់សំរាម ៣០", category: "HOM", brand: "Lotus Home", unit: "PKT", price: 1.9, cost: 1.15, reorder: 10, max: 60, stock: 31 },
  { sku: "PCR-7001", nameEn: "Shampoo 340 ml", nameKm: "សាប៊ូកក់សក់ ៣៤០ មល", category: "PCR", brand: "SilkSoft", unit: "BTL", price: 4.5, cost: 2.9, reorder: 10, max: 60, stock: 34 },
  { sku: "PCR-7002", nameEn: "Body Wash 500 ml", nameKm: "សាប៊ូងូតទឹក ៥០០ មល", category: "PCR", brand: "SilkSoft", unit: "BTL", price: 5.2, cost: 3.4, reorder: 8, max: 48, stock: 4 },
  { sku: "PCR-7003", nameEn: "Toothpaste 150 g", nameKm: "ថ្នាំដុសធ្មេញ ១៥០ក្រាម", category: "PCR", brand: "SilkSoft", unit: "PCS", price: 1.95, cost: 1.2, reorder: 15, max: 90, stock: 55 },
  { sku: "PCR-7004", nameEn: "Hand Sanitizer 250 ml", nameKm: "ជែលលាងដៃ ២៥០ មល", category: "PCR", brand: "SilkSoft", unit: "BTL", price: 2.75, cost: 1.5, reorder: 6, max: 30, stock: 120 },
  { sku: "SRV-9001", nameEn: "Gift Wrapping", nameKm: "សេវាខ្ចប់អំណោយ", category: "SRV", brand: null, unit: "SVC", price: 1.0, cost: 0, reorder: 0, max: 0, stock: 0, service: true },
  { sku: "SRV-9002", nameEn: "Local Delivery", nameKm: "សេវាដឹកជញ្ជូន", category: "SRV", brand: null, unit: "SVC", price: 2.5, cost: 0, reorder: 0, max: 0, stock: 0, service: true },
];

export const VARIANT_PARENT = {
  sku: "APP-8000",
  nameEn: "Cotton T-Shirt",
  nameKm: "អាវយឺតកប្បាស",
  price: 8.5,
  cost: 4.75,
  colours: ["Navy", "White"],
  sizes: ["M", "L"],
};

export const CUSTOMER_NAMES = [
  "Sok Dara", "Chan Vanna", "Keo Sreymom", "Lim Piseth", "Heng Sophea", "Mao Rithy", "Nuon Kanha", "Ouk Bopha", "Prak Vuthy", "Seng Chenda", "Tep Malis", "Un Sovann", "Vong Narith", "Yim Sokunthea", "Bun Thida", "Choun Ratana", "Dy Mony", "Eng Lina", "Hour Sothea", "Kim Sreyneang",
];

export const WHOLESALE_CUSTOMERS = ["Toul Kork Mini Mart", "Boeung Keng Kang Cafe", "Riverside Guesthouse", "Sen Sok Canteen"];

export const SUPPLIERS = [
  { code: "SUP-001", nameEn: "Mekong Beverage Distribution Co., Ltd.", nameKm: "ក្រុមហ៊ុនចែកចាយភេសជ្ជៈមេគង្គ", contact: "Sar Vibol", phone: "023 880 112", terms: "Net 30", lead: 3, categories: ["BEV"] },
  { code: "SUP-002", nameEn: "Angkor Foods Trading", nameKm: "អង្គរហ្វូដ", contact: "Ly Sothea", phone: "023 991 204", terms: "Net 15", lead: 5, categories: ["GRC", "SNK"] },
  { code: "SUP-003", nameEn: "Tonle Dairy Products", nameKm: "ផលិតផលទឹកដោះគោទន្លេ", contact: "Pich Sreyleak", phone: "012 554 019", terms: "Net 7", lead: 2, categories: ["DRY"] },
  { code: "SUP-004", nameEn: "Lotus Home and Care Supply", nameKm: "ឡូតុស ហូម", contact: "Meas Dalin", phone: "012 776 330", terms: "Net 30", lead: 7, categories: ["HOM", "PCR"] },
  { code: "SUP-005", nameEn: "Kandal Fresh Farm", nameKm: "កសិដ្ឋានកណ្ដាល", contact: "Rin Sopheak", phone: "097 410 882", terms: "Cash on delivery", lead: 1, categories: ["FRU"] },
  { code: "SUP-006", nameEn: "Riel Wear Garments", nameKm: "រៀល វែរ", contact: "Touch Sambath", phone: "016 228 901", terms: "Net 45", lead: 14, categories: ["APP"] },
];

export const EXPENSE_CATEGORIES = [
  ["RENT", "Rent"], ["UTIL", "Utilities"], ["TRAN", "Transportation"], ["PACK", "Packaging"], ["REPR", "Repairs"], ["OTHR", "Other"],
] as const;

export const EXPENSE_SAMPLES: [string, string, number][] = [
  ["RENT", "Monthly shop rent", 1200], ["UTIL", "Electricity bill (EDC)", 340], ["UTIL", "Water supply bill", 48], ["UTIL", "Internet service", 55], ["TRAN", "Fuel for delivery van", 72], ["PACK", "Carrier bags (store use)", 36], ["REPR", "Air conditioner service", 85], ["OTHR", "Cleaning supplies", 24],
];
