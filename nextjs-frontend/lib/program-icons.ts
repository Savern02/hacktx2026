import {
  Accessibility,
  Apple,
  Baby,
  Briefcase,
  Bus,
  FileText,
  GraduationCap,
  HeartPulse,
  House,
  LifeBuoy,
  Medal,
  Receipt,
  Scale,
  Sprout,
  Store,
  Wallet,
  Wifi,
  Zap,
  type LucideIcon,
} from "lucide-react";

// Program category (from discovery) -> icon.
const BY_CATEGORY: Record<string, LucideIcon> = {
  food: Apple,
  housing: House,
  utilities: Zap,
  healthcare: HeartPulse,
  childcare: Baby,
  cash_assistance: Wallet,
  employment: Briefcase,
  education: GraduationCap,
  transportation: Bus,
  seniors: HeartPulse,
  disability: Accessibility,
  veterans: Medal,
  tax_relief: Receipt,
  legal_aid: Scale,
  disaster_relief: LifeBuoy,
  internet: Wifi,
  small_business: Store,
};

// Federal programs have no categories, so fall back to words in the name.
// More specific patterns come first ("school lunch" is food, not education).
const BY_NAME: [RegExp, LucideIcon][] = [
  [/nutrition|snap|wic\b|food|lunch|breakfast|meal/i, Apple],
  [/energy|liheap|weatheriz|utilit|electric|heating/i, Zap],
  [
    /housing|rent|section 8|voucher|home ?owner|home repair|home loan|manufactured home|homeless|mortgage|continuum of care|property improvement/i,
    House,
  ],
  [/farm|crop|dairy|ranch|livestock|agricultur|biomass|conservation/i, Sprout],
  [
    /medicaid|medicare|health|chip\b|champva|telemedicine|connected care|insurance program|prescription/i,
    HeartPulse,
  ],
  [/head start|child ?care|infant|family unification/i, Baby],
  [/veteran|\bva\b|cemeter|headstone|paralympic/i, Medal],
  [/disab|blind/i, Accessibility],
  [
    /pell|student|scholar|fellowship|education|school|universit|learning|language|work-study/i,
    GraduationCap,
  ],
  [
    /unemployment|job|employment|training|workforce|workers|compensation|railroad|americorps|women's bureau/i,
    Briefcase,
  ],
  [
    /tanf|needy families|social security|supplemental security|pension|cash/i,
    Wallet,
  ],
  [/transit|transport/i, Bus],
  [/internet|broadband|lifeline|phone/i, Wifi],
  [/legal|rights settlement/i, Scale],
  [
    /disaster|emergency|flood|victim|trafficking|torture|safety officer/i,
    LifeBuoy,
  ],
  [/tax/i, Receipt],
  [/loan|credit|fund|grant/i, Wallet], // generic money help, last
];

export function programIcon(program: {
  name: string;
  categories?: string[] | null;
}): LucideIcon {
  for (const category of program.categories ?? []) {
    if (BY_CATEGORY[category]) return BY_CATEGORY[category];
  }
  return (
    BY_NAME.find(([pattern]) => pattern.test(program.name))?.[1] ?? FileText
  );
}
