export default function EmptyState({ icon: Icon, title, description }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-slate-300 py-10 text-center text-slate-500">
      {Icon && <Icon className="h-8 w-8" aria-hidden />}
      <p className="text-sm font-medium text-slate-600">{title}</p>
      {description && <p className="max-w-xs text-xs">{description}</p>}
    </div>
  );
}
