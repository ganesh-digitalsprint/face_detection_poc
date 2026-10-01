import { useId, useRef, useState } from 'react';
import { ImageUp, Video, X } from 'lucide-react';
import useObjectUrl from '../../hooks/useObjectUrl.js';
import { formatBytes } from '../../utils/formatters.js';

// Backend caps: images 10 MB (dependencies.MAX_UPLOAD_BYTES), video 500 MB (MAX_VIDEO_UPLOAD_MB default).
export const IMAGE_MAX_BYTES = 10 * 1024 * 1024;
export const VIDEO_MAX_BYTES = 500 * 1024 * 1024;
const IMAGE_TYPES = ['image/jpeg', 'image/png'];

/**
 * Drag & drop / click uploader for images (default) or video (`kind="video"`).
 * Controlled: parent owns `file`; `onChange(file|null)`.
 */
export default function ImageUploader({ file, onChange, disabled = false, kind = 'image', label }) {
  const inputId = useId();
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [validation, setValidation] = useState(null);
  const previewUrl = useObjectUrl(file);
  const isVideo = kind === 'video';
  const noun = isVideo ? 'video' : 'image';

  const accept = (candidate) => {
    if (!candidate) return;
    if (isVideo ? !candidate.type.startsWith('video/') : !IMAGE_TYPES.includes(candidate.type)) {
      setValidation(isVideo ? 'Please choose a video file (MP4 recommended).' : 'Unsupported file. Use JPG, JPEG or PNG.');
      return;
    }
    const maxBytes = isVideo ? VIDEO_MAX_BYTES : IMAGE_MAX_BYTES;
    if (candidate.size > maxBytes) {
      setValidation(`File is ${formatBytes(candidate.size)}; the maximum is ${formatBytes(maxBytes)}.`);
      return;
    }
    setValidation(null);
    onChange(candidate);
  };

  const reset = () => {
    setValidation(null);
    onChange(null);
    if (inputRef.current) inputRef.current.value = '';
  };

  const onDrop = (event) => {
    event.preventDefault();
    setDragging(false);
    if (!disabled) accept(event.dataTransfer.files?.[0]);
  };

  return (
    <div>
      <label htmlFor={inputId} className="mb-1 block text-sm font-medium text-slate-700">
        {label ?? (isVideo ? 'Video' : 'Face image')}
      </label>

      {file ? (
        <div className="relative overflow-hidden rounded-lg border border-slate-200 bg-slate-900">
          {isVideo ? (
            <video src={previewUrl ?? undefined} controls className="max-h-72 w-full" />
          ) : (
            <img src={previewUrl ?? undefined} alt={`Selected ${file.name}`} className="mx-auto max-h-72 object-contain" />
          )}
          <button
            type="button"
            onClick={reset}
            disabled={disabled}
            aria-label={`Remove ${noun}`}
            className="absolute right-2 top-2 rounded-full bg-white/90 p-1 text-slate-700 shadow hover:bg-white disabled:opacity-50"
          >
            <X className="h-4 w-4" />
          </button>
          <p className="bg-white px-3 py-1.5 text-xs text-slate-600">
            {file.name} · {formatBytes(file.size)}
          </p>
        </div>
      ) : (
        <div
          onDragOver={(e) => { e.preventDefault(); if (!disabled) setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`flex flex-col items-center gap-2 rounded-lg border-2 border-dashed px-4 py-10 text-center transition-colors ${
            dragging ? 'border-brand bg-blue-50' : 'border-slate-300 bg-slate-50'
          }`}
        >
          {isVideo ? <Video className="h-8 w-8 text-slate-400" aria-hidden /> : <ImageUp className="h-8 w-8 text-slate-400" aria-hidden />}
          <p className="text-sm text-slate-600">Drag &amp; drop {noun} here</p>
          <p className="text-xs text-slate-400">or</p>
          <button
            type="button"
            disabled={disabled}
            onClick={() => inputRef.current?.click()}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Choose {isVideo ? 'Video' : 'Image'}
          </button>
          <p className="text-xs text-slate-400">
            {isVideo ? `Supported: MP4 / browser-readable video · max ${formatBytes(VIDEO_MAX_BYTES)}` : `Supported: JPG / JPEG / PNG · max ${formatBytes(IMAGE_MAX_BYTES)}`}
          </p>
        </div>
      )}

      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept={isVideo ? 'video/*' : IMAGE_TYPES.join(',')}
        className="sr-only"
        disabled={disabled}
        onChange={(e) => accept(e.target.files?.[0])}
      />
      {validation && <p role="alert" className="mt-2 text-sm text-red-600">{validation}</p>}
    </div>
  );
}
