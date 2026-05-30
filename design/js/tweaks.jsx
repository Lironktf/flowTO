/* ============================================================
   FlowTO — Tweaks panel (React island, bridges to FlowTO.app)
   ============================================================ */
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "light",
  "density": "comfortable",
  "intensity": 1.0,
  "extrude": 1.3,
  "tilt": 52
}/*EDITMODE-END*/;

function FlowToTweaks() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);

  // expose the setter so the header theme toggle can keep the panel in sync
  React.useEffect(() => { window.FlowTO._tweakSetter = setTweak; }, [setTweak]);

  // push every change into the vanilla app + remember for post-load apply
  React.useEffect(() => {
    window.FlowTO._tweaks = t;
    if (window.FlowTO.app) window.FlowTO.app.applyTweaks(t);
  }, [t]);

  return (
    <TweaksPanel title="Tweaks">
      <TweakSection label="Theme" />
      <TweakRadio label="Map theme" value={t.theme} options={['light', 'dark']}
                  onChange={(v) => setTweak('theme', v)} />
      <TweakRadio label="Panel density" value={t.density} options={['comfortable', 'compact']}
                  onChange={(v) => setTweak('density', v)} />

      <TweakSection label="3-D map" />
      <TweakSlider label="Building height" value={t.extrude} min={0.5} max={2.6} step={0.1} unit="×"
                   onChange={(v) => setTweak('extrude', v)} />
      <TweakSlider label="Camera tilt" value={t.tilt} min={0} max={65} step={1} unit="°"
                   onChange={(v) => setTweak('tilt', v)} />

      <TweakSection label="Congestion scale" />
      <TweakSlider label="Pressure intensity" value={t.intensity} min={0.7} max={1.4} step={0.05} unit="×"
                   onChange={(v) => setTweak('intensity', v)} />
    </TweaksPanel>
  );
}

ReactDOM.createRoot(document.getElementById('tweaks-root')).render(<FlowToTweaks />);
