'use strict';

function allowsMicrophone({ trustedContents, currentUrl, pageUrl }, permission, details, check = false) {
  if (!trustedContents || currentUrl !== pageUrl || permission !== 'media' || details?.isMainFrame !== true || details?.requestingUrl !== pageUrl) return false;
  // Electron permission checks use mediaType; requests use mediaTypes.
  if (check) return details.mediaType === 'audio';
  return Array.isArray(details.mediaTypes) && details.mediaTypes.length === 1 && details.mediaTypes[0] === 'audio';
}

module.exports = { allowsMicrophone };
