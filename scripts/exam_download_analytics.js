(() => {
  const measurementId = document.currentScript?.dataset.measurementId;
  const preference = document.getElementById("download-analytics-enabled");
  if (!/^G-[A-Z0-9]+$/.test(measurementId ?? "") || !preference) return;

  const key = "anki-pipeline-download-analytics";
  const disableFlag = "ga-disable-" + measurementId;
  let tagLoaded = false;

  function gtag() { window.dataLayer.push(arguments); }

  function allowAnalytics(allowed) {
    window[disableFlag] = !allowed;
    if (!allowed || tagLoaded) return;
    tagLoaded = true;
    window.dataLayer = window.dataLayer || [];
    gtag("js", new Date());
    gtag("config", measurementId, {
      send_page_view: false,
      allow_google_signals: false,
      allow_ad_personalization_signals: false,
    });
    const tag = document.createElement("script");
    tag.async = true;
    tag.src = "https://www.googletagmanager.com/gtag/js?id=" + measurementId;
    document.head.append(tag);
  }

  try { preference.checked = localStorage.getItem(key) === "yes"; } catch {}
  allowAnalytics(preference.checked);
  preference.addEventListener("change", () => {
    try { localStorage.setItem(key, preference.checked ? "yes" : "no"); } catch {}
    allowAnalytics(preference.checked);
  });

  function recordDownload(event) {
    if (!preference.checked || event.defaultPrevented || (event.type === "auxclick" && event.button !== 1)) return;
    const link = event.target.closest?.("a[data-download-slot]");
    if (!link) return;
    gtag("event", "release_download_click", {
      download_slot: link.dataset.downloadSlot,
      page_location: location.origin + location.pathname,
      send_to: measurementId,
    });
  }

  document.addEventListener("click", recordDownload);
  document.addEventListener("auxclick", recordDownload);
})();
