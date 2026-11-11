import { mergeById } from './alertServiceModel.js';

/** Merge two server-filtered status streams without dropping rows at page boundaries. */
export async function statusGroupPage(fetchPage, params, signal) {
  const statuses = params.group === 'HISTORY' ? ['RESOLVED','DISMISSED'] : ['OPEN','ACKNOWLEDGED'];
  const { group, cursor, ...filters } = params;
  const previous = cursor ? JSON.parse(cursor) : {};
  const readStream = async (status, old) => {
    if (old?.items?.length || old?.done) return { ...old, status };
    const page = await fetchPage({ ...filters, status, ...(old?.cursor ? { cursor: old.cursor } : {}) }, signal);
    return { status, items: page.items, cursor: page.nextCursor, done: !page.hasMore };
  };
  const streams = await Promise.all(statuses.map((status) => readStream(status, previous[status])));
  const limit = params.limit || 25;
  const compare = (a,b) => {
    const order = String(b.occurredAt).localeCompare(String(a.occurredAt)) || String(b.id).localeCompare(String(a.id));
    return params.sort === 'oldest' ? -order : order;
  };
  const items = [];
  for (let i = 0; i < limit; i += 1) {
    for (let j = 0; j < streams.length; j += 1) {
      if (!streams[j].items.length && !streams[j].done) streams[j] = await readStream(streams[j].status, streams[j]);
    }
    const available = streams.filter((stream) => stream.items.length).sort((a,b) => compare(a.items[0],b.items[0]));
    if (!available.length) break;
    items.push(available[0].items.shift());
  }
  const hasMore = streams.some((stream) => stream.items.length || !stream.done);
  return { items: mergeById([],items,false), hasMore,
    nextCursor: hasMore ? JSON.stringify(Object.fromEntries(streams.map(({ status, ...value }) => [status,value]))) : null };
}
