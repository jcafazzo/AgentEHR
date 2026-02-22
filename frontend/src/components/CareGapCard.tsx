'use client';

interface CareGap {
  type: string;
  description: string;
  priority: 'high' | 'routine' | 'low';
}

interface CareGapCardProps {
  gap: CareGap;
  onAddress?: () => void;
}

const priorityColors = {
  high: 'border-red-300 bg-red-50 text-red-800',
  routine: 'border-amber-300 bg-amber-50 text-amber-800',
  low: 'border-slate-300 bg-slate-50 text-slate-700',
};

const typeIcons: Record<string, string> = {
  immunization: '💉',
  lab: '🧪',
  referral: '📋',
  screening: '🔍',
};

export function CareGapCard({ gap, onAddress }: CareGapCardProps) {
  return (
    <div className={`border rounded-lg p-3 mb-2 ${priorityColors[gap.priority]}`}>
      <div className="flex items-start gap-2">
        <span className="text-sm">{typeIcons[gap.type] || '⚠️'}</span>
        <div className="flex-1">
          <p className="text-sm font-medium">{gap.description}</p>
          {onAddress && (
            <button
              onClick={onAddress}
              className="text-xs mt-2 text-cyan-600 hover:text-cyan-700 font-medium"
            >
              Address this →
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
