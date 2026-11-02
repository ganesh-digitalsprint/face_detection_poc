const OPTIONS = [
  { key: 'faceBox', label: 'Face box' },
  { key: 'landmarks', label: 'Landmarks' },
  { key: 'labels', label: 'Coordinate labels' },
  { key: 'axes', label: 'Center axes' },
];

export default function OverlayToggles({ toggles, onChange }) {
  return (
    <fieldset className="vault-card p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <legend className="vault-heading float-left text-base">Overlay options</legend>
        <span className="text-xs text-[#55607A]">Applies to the video only</span>
      </div>
      <div className="clear-both flex flex-wrap gap-2">
        {OPTIONS.map(({ key, label }) => (
          <label key={key}
            className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-lg border border-[#E3E7F0] px-4 text-sm font-medium text-[#0F1B3D] hover:bg-[#F4F6FB] has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-[#34479B]">
            <input type="checkbox" className="h-4 w-4 accent-[#34479B]" checked={toggles[key]}
              onChange={(e) => onChange(key, e.target.checked)} />
            {label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
