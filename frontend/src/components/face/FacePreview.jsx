import useObjectUrl from '../../hooks/useObjectUrl.js';

export default function FacePreview({ file, alt = 'Face preview' }) {
  const url = useObjectUrl(file);
  if (!url) return null;
  return <img src={url} alt={alt} className="h-24 w-24 rounded-md border border-slate-200 object-cover" />;
}
