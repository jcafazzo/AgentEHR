'use client';

interface StatusPillProps {
  label: string;
  count?: number;
  color: 'red' | 'blue' | 'amber' | 'green' | 'orange' | 'slate';
  onClick?: () => void;
}

const colorClasses = {
  red: 'bg-red-100 text-red-700 border-red-200',
  blue: 'bg-blue-100 text-blue-700 border-blue-200',
  amber: 'bg-amber-100 text-amber-700 border-amber-200',
  green: 'bg-green-100 text-green-700 border-green-200',
  orange: 'bg-orange-100 text-orange-700 border-orange-200',
  slate: 'bg-slate-100 text-slate-700 border-slate-200',
};

export function StatusPill({ label, count, color, onClick }: StatusPillProps) {
  const classes = colorClasses[color];

  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border ${classes} hover:opacity-80 transition-opacity`}
    >
      <span>{label}</span>
      {count !== undefined && (
        <span className="font-bold">{count}</span>
      )}
    </button>
  );
}
