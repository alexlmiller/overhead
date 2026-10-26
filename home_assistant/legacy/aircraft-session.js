// Loaded as an HA dashboard resource. Only the explicitly launched TV URL
// may request return to Art; leaving this page removes its timer.
class OfficeAircraftSession extends HTMLElement {
  setConfig() {
    if (!this.card) {
      this.card = document.createElement('ha-card');
      this.card.style.cssText = 'padding:16px;font-size:16px';
      this.appendChild(this.card);
    }
  }

  set hass(value) {
    this._hass = value;
    this.lastUpdate = Date.now();
    this.tick();
  }

  connectedCallback() {
    this.timer = setInterval(() => this.tick(), 1000);
  }

  disconnectedCallback() {
    clearInterval(this.timer);
    this.missingSince = null;
  }

  getCardSize() { return 1; }

  tick() {
    const now = Date.now();
    const s = this._hass?.states;
    if (!s || !this.card) return;
    const automatic = s['input_select.office_aircraft_session']?.state === 'Automatic';
    const missing = s['sensor.office_aircraft_current']?.state === 'none';
    const activePage = this.isConnected && document.visibilityState === 'visible' &&
      location.pathname === '/dashboard-office-aircraft/sky' &&
      new URLSearchParams(location.search).get('office_tv') === '1';
    const freshConnection = this._hass.connected && now - this.lastUpdate < 15000;
    if (!(automatic && missing && activePage && freshConnection)) {
      this.missingSince = null;
    } else if (this.missingSince == null) {
      this.missingSince = now;
    }
    this.card.textContent = automatic
      ? (missing ? 'Aircraft has left — returning to Art shortly' : 'Following aircraft · cameras and manual controls take priority')
      : 'Manual view · stays open until you change it';
    if (this.missingSince != null && now - this.missingSince >= 15000 &&
        now - (this.lastAttempt || 0) >= 5000) {
      // The HA script independently checks TV/app/house/session and the
      // server-side missing duration. Retry briefly if those updates raced.
      this.lastAttempt = now;
      this._hass.callService('script', 'office_tv_aircraft_finished').catch(() => {});
    }
  }
}
if (!customElements.get('office-aircraft-session')) {
  customElements.define('office-aircraft-session', OfficeAircraftSession);
}
