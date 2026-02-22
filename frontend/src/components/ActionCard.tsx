'use client';

interface ActionableItem {
  id: string;
  type: 'order' | 'referral' | 'update_record' | 'documentation';
  description: string;
  priority: 'high' | 'routine' | 'low';
  reason: string;
  status: 'suggested' | 'queued' | 'approved' | 'rejected';
}

interface ActionCardProps {
  action: ActionableItem;
  onApprove?: () => void;
  onReject?: () => void;
  onQueue?: () => void;
}

const priorityColors = {
  high: 'border-l-red-500 bg-red-50',
  routine: 'border-l-cyan-500 bg-cyan-50',
  low: 'border-l-slate-400 bg-slate-50',
};

const typeIcons = {
  order: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
    </svg>
  ),
  referral: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8h2a2 2 0 012 2v6a2 2 0 01-2 2h-2v4l-4-4H9a1.994 1.994 0 01-1.414-.586m0 0L11 14h4a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2v4l.586-.586z" />
    </svg>
  ),
  update_record: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
    </svg>
  ),
  documentation: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
    </svg>
  ),
};

export function ActionCard({ action, onApprove, onReject, onQueue }: ActionCardProps) {
  return (
    <div className={`border-l-4 ${priorityColors[action.priority]} rounded-r-lg p-3 mb-2`}>
      <div className="flex items-start gap-2">
        <span className="text-slate-600 mt-0.5">{typeIcons[action.type]}</span>
        <div className="flex-1 min-w-0">
          <p className="font-medium text-slate-800 text-sm">{action.description}</p>
          <p className="text-xs text-slate-500 mt-1 line-clamp-2">{action.reason}</p>
        </div>
      </div>
      {action.status === 'suggested' && (
        <div className="flex gap-2 mt-3">
          {onQueue && (
            <button
              onClick={onQueue}
              className="text-xs bg-cyan-500 hover:bg-cyan-600 text-white px-3 py-1 rounded transition-colors"
            >
              Queue
            </button>
          )}
          {onApprove && (
            <button
              onClick={onApprove}
              className="text-xs bg-green-500 hover:bg-green-600 text-white px-3 py-1 rounded transition-colors"
            >
              Approve Now
            </button>
          )}
          {onReject && (
            <button
              onClick={onReject}
              className="text-xs text-slate-500 hover:text-red-500 transition-colors"
            >
              Dismiss
            </button>
          )}
        </div>
      )}
      {action.status === 'queued' && (
        <div className="flex items-center gap-2 mt-2">
          <span className="text-xs text-cyan-600 font-medium">Queued for approval</span>
        </div>
      )}
    </div>
  );
}
