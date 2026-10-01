import StatusBadge from '../common/StatusBadge.jsx';
import { formatScore } from '../../utils/formatters.js';

/** One identified face. `similarity` and `distance` are raw scores, NOT probabilities. */
export default function RecognitionResult({ result, index }) {
  return (
    <li className="rounded-md border border-slate-200 p-4 text-sm">
      <div className="mb-2 flex items-center justify-between">
        <p className="font-semibold">Face #{index + 1}</p>
        <StatusBadge status={result.matched ? 'MATCH' : 'UNKNOWN'} />
      </div>
      <dl className="grid grid-cols-[8rem_1fr] gap-y-1">
        <dt className="text-slate-500">Identity</dt>
        <dd>{result.matched ? result.person_code : 'Unknown'}</dd>
        {result.matched && (<><dt className="text-slate-500">Name</dt><dd>{result.name}</dd></>)}
        <dt className="text-slate-500">Similarity Score</dt>
        <dd>{formatScore(result.similarity)}</dd>
        <dt className="text-slate-500">Distance</dt>
        <dd>{formatScore(result.distance)} <span className="text-xs text-slate-400">(lower = more alike)</span></dd>
      </dl>
    </li>
  );
}
