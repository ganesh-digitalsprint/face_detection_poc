import ImageUploader from '../face/ImageUploader.jsx';

export const SLOTS = [
  { key: 'front', label: 'Front Face (required)' },
  { key: 'left', label: 'Left Angle (recommended)' },
  { key: 'right', label: 'Right Angle (recommended)' },
];

export default function ImageEnrollmentPanel({ files, disabled, onChange }) {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {SLOTS.map((slot) => (
        <ImageUploader
          key={slot.key}
          label={slot.label}
          file={files[slot.key]}
          disabled={disabled}
          onChange={(file) => onChange(slot.key, file)}
        />
      ))}
    </div>
  );
}
