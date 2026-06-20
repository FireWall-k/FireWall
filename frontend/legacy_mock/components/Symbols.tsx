import React from "react";

// 데모용 단순 픽토그램 세트. 실제로는 ARASAAC/KAAC API에서 가져온 이미지가 들어갈 자리.
// 명세서 §3-5 상징 매핑 전략의 결과물을 시각적으로 흉내낸 것.

type IconProps = { className?: string };

export const SymbolBox: React.FC<IconProps> = ({ className }) => (
  <svg viewBox="0 0 100 100" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="15" y="35" width="70" height="50" rx="3" fill="#D98B5F" />
    <rect x="15" y="35" width="70" height="14" fill="#C4703E" />
    <path d="M15 35 L50 18 L85 35" stroke="#A35A2E" strokeWidth="4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    <line x1="50" y1="49" x2="50" y2="85" stroke="#A35A2E" strokeWidth="3" />
  </svg>
);

export const SymbolLook: React.FC<IconProps> = ({ className }) => (
  <svg viewBox="0 0 100 100" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="50" cy="38" r="22" fill="#F2EEE3" stroke="#1A1A1A" strokeWidth="4" />
    <circle cx="50" cy="38" r="9" fill="#2C6E49" />
    <path d="M28 38 Q50 20 72 38" stroke="#1A1A1A" strokeWidth="4" fill="none" strokeLinecap="round" />
    <path d="M28 38 Q50 56 72 38" stroke="#1A1A1A" strokeWidth="4" fill="none" strokeLinecap="round" />
    <path d="M30 78 Q50 60 70 78" stroke="#1A1A1A" strokeWidth="5" fill="none" strokeLinecap="round" />
  </svg>
);

export const SymbolMoveRight: React.FC<IconProps> = ({ className }) => (
  <svg viewBox="0 0 100 100" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="10" y="40" width="35" height="28" rx="3" fill="#D98B5F" />
    <path d="M50 54 L82 54 M82 54 L70 42 M82 54 L70 66" stroke="#2C6E49" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    <rect x="55" y="62" width="28" height="22" rx="3" fill="#7A9471" opacity="0.4" />
  </svg>
);

export const SymbolStack: React.FC<IconProps> = ({ className }) => (
  <svg viewBox="0 0 100 100" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="25" y="65" width="50" height="16" rx="2" fill="#C4703E" />
    <rect x="25" y="47" width="50" height="16" rx="2" fill="#D98B5F" />
    <rect x="25" y="29" width="50" height="16" rx="2" fill="#E0A030" />
    <path d="M50 18 L50 28 M44 23 L50 18 L56 23" stroke="#1A1A1A" strokeWidth="4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const SymbolCheck: React.FC<IconProps> = ({ className }) => (
  <svg viewBox="0 0 100 100" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="50" cy="50" r="40" fill="#2C6E49" />
    <path d="M30 52 L44 66 L72 36" stroke="white" strokeWidth="8" fill="none" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const SymbolGeneric: React.FC<IconProps> = ({ className }) => (
  <svg viewBox="0 0 100 100" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="20" y="20" width="60" height="60" rx="10" fill="#E6E0D2" stroke="#647168" strokeWidth="3" />
    <circle cx="50" cy="50" r="16" fill="#7A9471" />
  </svg>
);

export const symbolFor = (actionType: string): React.FC<IconProps> => {
  switch (actionType) {
    case "observe": return SymbolLook;
    case "move": return SymbolMoveRight;
    case "stack": return SymbolStack;
    case "check": return SymbolCheck;
    case "pick": return SymbolBox;
    case "place": return SymbolMoveRight;
    default: return SymbolGeneric;
  }
};
