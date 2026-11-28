/* global_search.js - Palette de recherche rapide globale (Ctrl+K / Cmd+K) */
(function () {
  let catalogue = null;
  let chargementEnCours = false;
  let resultatsFiltres = [];
  let indexSelection = 0;

  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));

  function injecterStylesEtModale() {
    if (document.getElementById('tq-search-modal')) return;

    const style = document.createElement('style');
    style.textContent = `
      .tq-k-overlay {
        position: fixed; inset: 0; z-index: 9999;
        background: rgba(0, 0, 0, 0.58);
        display: none; align-items: flex-start; justify-content: center;
        padding-top: 9vh;
      }
      .tq-k-overlay.ouvert { display: flex; }
      .tq-k-box {
        width: min(680px, 94vw);
        background: var(--surface, #1a1a18);
        border: 1px solid var(--trait, #2d2c29);
        border-radius: 8px;
        box-shadow: 0 20px 50px rgba(0, 0, 0, 0.45);
        overflow: hidden;
        color: var(--encre, #ece8df);
        font-family: inherit;
      }
      .tq-k-head {
        display: flex; align-items: center; gap: 10px;
        padding: 12px 16px;
        border-bottom: 1px solid var(--trait, #2d2c29);
        background: var(--surface-alt, var(--papier, #121211));
      }
      .tq-k-input {
        flex: 1; background: transparent; border: none; outline: none;
        color: var(--encre, #ece8df); font-size: 15px;
      }
      .tq-k-kbd {
        font-size: 11px; color: var(--muted, #98948a);
        background: var(--surface, #1a1a18);
        border: 1px solid var(--trait, #2d2c29);
        border-radius: 4px; padding: 2px 6px;
      }
      .tq-k-list {
        max-height: 410px; overflow-y: auto;
      }
      .tq-k-item {
        display: flex; justify-content: space-between; align-items: center; gap: 12px;
        padding: 10px 16px;
        border-bottom: 1px solid var(--trait, #2d2c29);
        cursor: pointer;
      }
      .tq-k-item:hover, .tq-k-item.actif { background: var(--marine-pale, rgba(228, 222, 206, 0.09)); }
      .tq-k-left { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
      .tq-k-top { display: flex; align-items: center; gap: 8px; }
      .tq-k-tk { font-weight: 700; color: var(--marine, #e4dece); font-size: 14px; }
      .tq-k-nom { color: var(--encre, #ece8df); font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .tq-k-meta { font-size: 11.5px; color: var(--muted, #98948a); }
      .tq-k-right { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
      .tq-k-prix { font-weight: 600; font-size: 13.5px; color: var(--encre, #ece8df); }
      .tq-k-foot {
        display: flex; justify-content: space-between; align-items: center;
        padding: 8px 16px; font-size: 11.5px; color: var(--muted, #98948a);
        background: var(--surface-alt, var(--papier, #121211));
        border-top: 1px solid var(--trait, #2d2c29);
      }
      .tq-k-empty { padding: 24px 16px; text-align: center; color: var(--muted, #98948a); font-size: 13.5px; }
    `;
    document.head.appendChild(style);

    const overlay = document.createElement('div');
    overlay.id = 'tq-search-modal';
    overlay.className = 'tq-k-overlay';
    overlay.innerHTML = `
      <div class="tq-k-box" role="dialog" aria-modal="true" aria-label="Recherche globale de titres">
        <div class="tq-k-head">
          <input type="text" id="tq-k-input" class="tq-k-input" placeholder="Rechercher un ticker, une société, un indice ou un secteur…" autocomplete="off" />
          <a href="/run?indice=Tous%20les%20march%C3%A9s" class="tq-k-kbd" style="text-decoration:none;">Tous les marchés</a>
          <span class="tq-k-kbd">Échap</span>
        </div>
        <div id="tq-k-list" class="tq-k-list"></div>
        <div class="tq-k-foot">
          <span id="tq-k-count">Chargement du catalogue…</span>
          <span>↑ ↓ Naviguer &nbsp;·&nbsp; Entrée Ouvrir</span>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    overlay.addEventListener('click', e => {
      if (e.target === overlay) fermerRecherche();
    });

    const input = document.getElementById('tq-k-input');
    input.addEventListener('input', () => filtrerCatalogue(input.value));
    input.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (resultatsFiltres.length) {
          indexSelection = (indexSelection + 1) % resultatsFiltres.length;
          rendreResultats();
        }
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (resultatsFiltres.length) {
          indexSelection = (indexSelection - 1 + resultatsFiltres.length) % resultatsFiltres.length;
          rendreResultats();
        }
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const cible = resultatsFiltres[indexSelection];
        if (cible) ouvrirAction(cible);
      } else if (e.key === 'Escape') {
        fermerRecherche();
      }
    });
  }

  async function chargerCatalogue() {
    if (catalogue || chargementEnCours) return;
    chargementEnCours = true;
    try {
      const r = await fetch('/api/search/catalog');
      if (r.ok) {
        const data = await r.json();
        catalogue = Array.isArray(data.items) ? data.items : [];
      } else {
        catalogue = [];
      }
    } catch (e) {
      catalogue = [];
    } finally {
      chargementEnCours = false;
      const input = document.getElementById('tq-k-input');
      filtrerCatalogue(input ? input.value : '');
    }
  }

  function filtrerCatalogue(requete) {
    const countEl = document.getElementById('tq-k-count');
    if (!catalogue) {
      if (countEl) countEl.textContent = 'Chargement du catalogue…';
      return;
    }
    const q = (requete || '').trim().toLowerCase();
    if (!q) {
      resultatsFiltres = catalogue.slice(0, 25);
      if (countEl) countEl.textContent = `${catalogue.length} titres en cache sur 20 indices`;
    } else {
      const termes = q.split(/\s+/);
      const matches = [];
      for (let i = 0; i < catalogue.length; i++) {
        const it = catalogue[i];
        const hay = `${it.ticker} ${it.nom} ${it.indice} ${it.continent} ${it.secteur}`.toLowerCase();
        if (termes.every(t => hay.includes(t))) {
          const scorePertinence = it.ticker.toLowerCase() === q ? 0 : (it.ticker.toLowerCase().startsWith(q) ? 1 : 2);
          matches.push({ it, scorePertinence });
        }
      }
      matches.sort((a, b) => a.scorePertinence - b.scorePertinence || a.it.ticker.localeCompare(b.it.ticker));
      resultatsFiltres = matches.slice(0, 30).map(m => m.it);
      if (countEl) countEl.textContent = `${matches.length} résultat(s) sur ${catalogue.length} titres`;
    }
    indexSelection = 0;
    rendreResultats();
  }

  function rendreResultats() {
    const listEl = document.getElementById('tq-k-list');
    if (!listEl) return;
    if (!resultatsFiltres.length) {
      listEl.innerHTML = '<div class="tq-k-empty">Aucun titre correspondant dans le cache.</div>';
      return;
    }
    listEl.innerHTML = resultatsFiltres.map((it, idx) => {
      const prixStr = typeof it.prix === 'number' ? `${it.prix.toFixed(2).replace('.', ',')} ${esc(it.devise)}` : '—';
      const capStr = typeof it.cap_usd_md === 'number' ? ` · Cap. ${it.cap_usd_md.toFixed(1).replace('.', ',')} Md$` : '';
      return `
        <div class="tq-k-item ${idx === indexSelection ? 'actif' : ''}" data-idx="${idx}">
          <div class="tq-k-left">
            <div class="tq-k-top">
              <span class="tq-k-tk">${esc(it.ticker)}</span>
              <span class="tq-k-nom">${esc(it.nom)}</span>
            </div>
            <div class="tq-k-meta">${esc(it.indice)} (${esc(it.continent)}) · ${esc(it.secteur)}${capStr}</div>
          </div>
          <div class="tq-k-right">
            <div class="tq-k-prix">${prixStr}</div>
          </div>
        </div>
      `;
    }).join('');

    listEl.querySelectorAll('.tq-k-item').forEach(el => {
      el.addEventListener('click', () => {
        const item = resultatsFiltres[parseInt(el.dataset.idx, 10)];
        if (item) ouvrirAction(item);
      });
    });

    const actifEl = listEl.querySelector('.tq-k-item.actif');
    if (actifEl) actifEl.scrollIntoView({ block: 'nearest' });
  }

  function ouvrirAction(item) {
    fermerRecherche();
    const indicesItem = Array.isArray(item.indices) && item.indices.length ? item.indices : (item.indice ? [item.indice] : []);
    const indiceCible = indicesItem[0] || 'Tous les marchés';
    const dejaSurBonMarche = window.CFG && (
      window.CFG.indice === 'Tous les marchés' || indicesItem.includes(window.CFG.indice)
    );
    if (dejaSurBonMarche && window.Quant && window.Quant.focaliserTicker) {
      window.Quant.focaliserTicker(item.ticker);
      return;
    }
    window.location.href = `/run?indice=${encodeURIComponent(indiceCible)}&focus=${encodeURIComponent(item.ticker)}`;
  }

  function ouvrirRecherche() {
    injecterStylesEtModale();
    const overlay = document.getElementById('tq-search-modal');
    overlay.classList.add('ouvert');
    const input = document.getElementById('tq-k-input');
    input.value = '';
    input.focus();
    chargerCatalogue();
    filtrerCatalogue('');
  }

  function fermerRecherche() {
    const overlay = document.getElementById('tq-search-modal');
    if (overlay) overlay.classList.remove('ouvert');
  }

  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      const overlay = document.getElementById('tq-search-modal');
      if (overlay && overlay.classList.contains('ouvert')) fermerRecherche();
      else ouvrirRecherche();
    }
  });

  document.addEventListener('click', e => {
    if (e.target.closest('[data-open-search]')) {
      e.preventDefault();
      ouvrirRecherche();
    }
  });

  window.TerminalSearch = { open: ouvrirRecherche, close: fermerRecherche };
})();