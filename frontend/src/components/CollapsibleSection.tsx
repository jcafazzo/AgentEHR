'use client';

import { useState } from 'react';

interface CollapsibleSectionProps {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  badge?: string;
  badgeColor?: 'red' | 'green' | 'amber' | 'slate';
}

const badgeColors = {
  red: 'text-red-600',
  green: 'text-green-600',
  amber: 'text-amber-600',
  slate: 'text-slate-500',
};

export function CollapsibleSection({
  title,
  children,
  defaultOpen = false,
  badge,
  badgeColor = 'slate',
}: CollapsibleSectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className="border-b border-slate-200 last:border-b-0">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between py-3 text-left hover:bg-slate-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-slate-700">{title}</span>
          {badge && (
            <span className={`text-xs ${badgeColors[badgeColor]}`}>{badge}</span>
          )}
        </div>
        <svg
          className={`w-4 h-4 text-slate-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {isOpen && (
        <div className="pb-4 text-sm">
          {children}
        </div>
      )}
    </div>
  );
}
