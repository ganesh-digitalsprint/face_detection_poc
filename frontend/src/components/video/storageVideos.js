export const availableStoredVideos = (files, accept = '.mp4,.avi,.mov,.mkv,.webm') => {
  const extensions = accept.toLowerCase().split(',').map((entry) => entry.trim()).filter(Boolean);
  return (files || []).filter((item) => ['sample_videos', 'uploads'].includes(item.category)
    && extensions.some((ext) => item.name.toLowerCase().endsWith(ext)));
};
