/* dashboard.js - Tableau de bord complet */
window.Quant = window.Quant || {};

function extraireDateMaj(row) {
  if (!row) return null;
  if (row.last_updated) {
    const parsed = new Date(row.last_updated);
    if (!Number.isNaN(parsed.getTime())) return parsed;
  }
  if (typeof row.maj === 'string') {
    const m = row.maj.trim().match(/^(?:(\d{2})\/(\d{2})(?:\/(\d{4}))?\s+)?(\d{2}):(\d{2})\s*UTC$/i);
    if (m) {
      const now = new Date();
      const annee = m[3] ? parseInt(m[3], 10) : now.getUTCFullYear();
      const mois = m[2] ? parseInt(m[2], 10) - 1 : now.getUTCMonth();
      const jour = m[1] ? parseInt(m[1], 10) : now.getUTCDate();
      const d = new Date(Date.UTC(annee, mois, jour, parseInt(m[4], 10), parseInt(m[5], 10)));
      if (!Number.isNaN(d.getTime())) return d;
    }
  }
  return null;
}

function formaterDateLocale(row) {
  const d = extraireDateMaj(row);
  if (!d) return (row && row.maj) ? row.maj : '—';
  const dateStr = d.toLocaleDateString([], { day: '2-digit', month: '2-digit' });
  const heureStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return `${dateStr} ${heureStr}`;
}

function tooltipDateLocale(row) {
  const d = extraireDateMaj(row);
  if (!d) return '';
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'heure locale';
  return `${d.toLocaleString([], {
    weekday: 'short',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })} (${tz})`;
}

$(function () {
  const CFG = window.CFG;
  if (window.Reglages && CFG && CFG.indice) {
    window.Reglages.set('dernier_indice', CFG.indice);
  }

  const urlParams = new URLSearchParams(window.location.search);
  let focusTicker = (urlParams.get('focus') || '').trim().toUpperCase();
  let focusAutoOuvert = false;

  const LISTES_DEFAUT = ['À renforcer', 'Long terme', 'Surveillance'];
  let watchlists = { lists: [...LISTES_DEFAUT], items: {} };
  try {
    const cacheWl = JSON.parse(localStorage.getItem('quant_watchlists') || 'null');
    if (cacheWl && Array.isArray(cacheWl.lists) && cacheWl.items) {
      watchlists = cacheWl;
    }
  } catch (e) {}

  const donnees = {};
  const lignes = {};
  const devisesVues = new Set();
  let total = 0, termine = false;

  const ND = '<span class="nd">–</span>';
  const vide = v => v === null || v === undefined || Number.isNaN(v);
  const fmt = (v, d = 1, suf = '') => vide(v) ? ND : Number(v).toFixed(d).replace('.', ',') + suf;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const SECTEURS_FR = {
    'Technology': 'Technologie', 'Healthcare': 'Santé', 'Financial Services': 'Finance',
    'Consumer Cyclical': 'Conso. cyclique', 'Consumer Defensive': 'Conso. défensive', 'Industrials': 'Industrie',
    'Energy': 'Énergie', 'Basic Materials': 'Matériaux', 'Utilities': 'Services publics',
    'Real Estate': 'Immobilier', 'Communication Services': 'Communication'
  };
  const classeSigne = v => vide(v) ? '' : (v > 0 ? 'pos' : (v < 0 ? 'neg' : ''));

  Object.assign(window.Quant, { donnees, esc, fmt, vide, SECTEURS_FR });

  function listesDuTicker(tk) {
    return Array.isArray(watchlists.items[tk]) ? watchlists.items[tk] : [];
  }

  function sauverWatchlistsLocal() {
    try { localStorage.setItem('quant_watchlists', JSON.stringify(watchlists)); } catch (e) {}
  }

  function synchroniserSelectWatchlists() {
    const sel = $('#f-fav');
    if (!sel.length) return;
    const valActuelle = sel.val();
    let html = '<option value="">Toutes</option><option value="__ANY__">Dans une liste (★)</option>';
    watchlists.lists.forEach(nom => {
      html += `<option value="${esc(nom)}">${esc(nom)}</option>`;
    });
    sel.html(html);
    if (valActuelle && sel.find(`option[value="${valActuelle.replace(/"/g, '\\"')}"]`).length) {
      sel.val(valActuelle);
    }
  }

  function rafraichirEtoiles() {
    $('.etoile').each(function () {
      const tk = this.dataset.ticker;
      const lst = listesDuTicker(tk);
      const actif = lst.length > 0;
      $(this).toggleClass('actif', actif);
      this.title = actif ? `Listes : ${lst.join(', ')}` : 'Ajouter à une liste de suivi';
      this.textContent = lst.length > 1 ? `★${lst.length}` : '★';
    });
  }

  synchroniserSelectWatchlists();

  fetch('/api/user/watchlists')
    .then(r => r.ok ? r.json() : null)
    .then(d => {
      if (d && Array.isArray(d.lists) && d.items) {
        watchlists = { lists: d.lists, items: d.items };
        sauverWatchlistsLocal();
        synchroniserSelectWatchlists();
        rafraichirEtoiles();
        if (typeof table !== 'undefined' && table.draw) {
          table.draw(false);
        }
      }
    }).catch(() => {});

  function colNum(champ, titre, aide, d, suf, classeFn) {
    return {
      data: champ, defaultContent: '', className: 'num', title: `<span title="${esc(aide)}">${titre}</span>`,
      render: (v, type, r) => {
        if (type === 'export') return vide(v) ? '' : v;
        if (type !== 'display') return vide(v) ? -1e12 : v;
        return vide(v) ? ND : `<span class="${classeFn ? classeFn(v, r) : ''}">${fmt(v, d, suf)}</span>`;
      }
    };
  }

  const dl = (label, valeur, aide) => `<div><dt title="${esc(aide || '')}">${label}</dt><dd>${valeur}</dd></div>`;

  const COLONNES = [
    { data: null, orderable: false, className: 't-g', title: '', width: '58px',
      render: (d, type, r) => {
        const lst = listesDuTicker(r.ticker);
        const actif = lst.length > 0;
        if (type !== 'display') return actif ? 1 : 0;
        const labelEtoile = lst.length > 1 ? `★${lst.length}` : '★';
        const tipEtoile = actif ? `Listes : ${lst.join(', ')}` : 'Ajouter à une liste de suivi';
        return `<i class="etoile ${actif ? 'actif' : ''}" data-ticker="${esc(r.ticker)}" role="button" tabindex="0" aria-label="Gérer les listes de suivi" title="${esc(tipEtoile)}">${labelEtoile}</i>`
          + `<button type="button" class="cmp ${(window.Quant && window.Quant.cmpSel || []).includes(r.ticker) ? 'actif' : ''}" data-ticker="${esc(r.ticker)}" title="Ajouter au comparateur" aria-label="Comparer ${esc(r.ticker)}">⇄</button>`;
      } },
    { data: 'ticker', className: 't-g', title: 'Titre',
      render: (v, type, r) => type === 'display' ? `<div class="titre"><strong>${esc(v)}</strong><span title="${esc(r.nom)}">${esc(r.nom)}</span></div>`
        : (type === 'filter' ? `${v} ${r.nom}` : v) },
    { data: 'secteur', className: 't-g', title: 'Secteur',
      render: (v, type) => {
        const nomFr = SECTEURS_FR[v] || v || '–';
        if (type === 'display') return esc(nomFr);
        if (type === 'filter') return `${v} ${nomFr}`;
        return v || '';
      } },
    { data: 'prix', defaultContent: '', className: 'num', title: 'Cours',
      render: (v, type, r) => type === 'display' ? `${fmt(v, 2)} <small>${esc(r.devise)}</small>` : (vide(v) ? -1e12 : v) },
    { data: 'score', defaultContent: '', className: 'num',
      title: '<span title="Rang percentile (0-100) du score composite parmi les titres analysés de ce marché. 90 = parmi les 10 % meilleurs.">Score</span>',
      render: (v, type) => {
        if (type === 'export') return vide(v) ? '' : v;
        if (type !== 'display') return vide(v) ? -1 : v;
        if (vide(v)) return termine ? ND : '<span class="nd">…</span>';
        return `<span class="score ${v >= 75 ? 'haut' : (v <= 30 ? 'bas' : 'moy')}">${v}</span>`;
      } },
    { data: null, orderable: false, className: 'num',
      title: '<span title="Profil du titre. De gauche à droite : Valorisation, Qualité, Croissance, Risque (haut = plus sûr), Momentum. Chaque barre est un percentile.">Profil</span>',
      render: (d, type, r) => {
        if (type !== 'display') return '';
        const noms = ['Valorisation', 'Qualité', 'Croissance', 'Risque (haut = sûr)', 'Momentum'];
        return '<span class="profil">' + ['valo', 'qual', 'crois', 'risq', 'mom'].map((k, i) => {
          const v = r[k];
          return vide(v) ? `<i class="vide" style="height:3px" title="${noms[i]} : n/d"></i>`
            : `<i style="height:${Math.max(3, Math.round(v * 0.22))}px" title="${noms[i]} : ${v}/100"></i>`;
        }).join('') + '</span>';
      } },
    { data: 'signal', defaultContent: '', className: 't-g', title: '<span title="Signal relatif à l\'indice : meilleurs scores + garde-fous (risque, détresse, marge de sécurité). Ce n\'est pas un conseil en investissement.">Signal</span>',
      render: (v, type) => {
        if (type !== 'display') return v || '';
        if (!v) return '<span class="nd">…</span>';
        const c = v.startsWith('ACHAT') ? 'pos' : (v === 'VENTE' ? 'neg' : (v === 'INSUFFISANT' ? 'nd' : ''));
        return `<span class="signal ${c}">${esc(v)}</span>`;
      } },
    colNum('marge_secu', 'Marge séc.', 'Marge de sécurité = (valeur estimée − cours) / valeur estimée.', 1, ' %', v => v > 15 ? 'pos' : (v < 0 ? 'neg' : '')),
    { data: 'valo_base', defaultContent: '', className: 'num', title: '<span title="Valeur par action, scénario central.">Valeur estimée</span>',
      render: (v, type, r) => {
        if (type === 'export') return vide(v) ? '' : v;
        if (type !== 'display') return vide(v) ? -1e12 : v;
        if (vide(v)) return ND;
        const fourchette = (!vide(r.valo_bear) && !vide(r.valo_bull)) ? `<br><small>${fmt(r.valo_bear, 0)} – ${fmt(r.valo_bull, 0)}</small>` : '';
        return `${fmt(v, 2)}${fourchette}`;
      } },
    colNum('spread', 'ROIC − WACC', 'Création de valeur : rentabilité du capital investi moins coût du capital.', 1, ' pts', classeSigne),
    colNum('fcf_yield', 'FCF yield', 'Free cash-flow / capitalisation boursière.', 1, ' %', classeSigne),
    colNum('per', 'PER', 'Cours / bénéfice par action (12 derniers mois).', 1, ''),
    colNum('cagr_ca', 'Croiss. CA 3 ans', 'Croissance annuelle moyenne du chiffre d\'affaires sur 3 ans.', 1, ' %', classeSigne),
    colNum('vol', 'Volatilité', 'Volatilité annualisée sur 1 an.', 0, ' %'),
    colNum('mom_12_1', 'Momentum 12-1', 'Performance sur 12 mois en excluant le dernier mois.', 0, ' %', classeSigne),
    {
      data: null,
      defaultContent: '',
      className: 'num',
      title: 'Mise à jour',
      render: function (_data, type, row) {
        if (type === 'sort' || type === 'type') {
          const d = extraireDateMaj(row);
          return d ? d.getTime() : 0;
        }
        const aff = formaterDateLocale(row);
        if (type === 'export') return aff;
        const tip = tooltipDateLocale(row);
        return tip ? `<span title="${esc(tip)}">${esc(aff)}</span>` : esc(aff);
      }
    }
  ];

  const COLS_EXPORT = [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14];

  const table = $('#tbl').DataTable({
    data: [], columns: COLONNES, pageLength: 100, order: [[4, 'desc']], autoWidth: false, deferRender: true, dom: 'Bfrtip',
    buttons: [
      { extend: 'csv', text: 'Exporter en CSV', exportOptions: { orthogonal: 'export', columns: COLS_EXPORT } },
      { extend: 'excel', text: 'Exporter en Excel', exportOptions: { orthogonal: 'export', columns: COLS_EXPORT } }
    ],
    language: { search: 'Rechercher :', lengthMenu: '_MENU_ lignes', info: '_TOTAL_ titres affichés', infoEmpty: 'Aucun titre',
      infoFiltered: '(sur _MAX_)', emptyTable: 'Chargement depuis le cache…',
      zeroRecords: 'Aucun titre ne correspond aux filtres actifs.', paginate: { previous: 'Précédent', next: 'Suivant' } }
  });

  window.Quant.table = table;

  /* ---------- Bannière d'isolation d'un titre (Ctrl+K) ---------- */
  function majBanniereFocus() {
    let banner = $('#focus-banner');
    if (!focusTicker) {
      banner.remove();
      return;
    }
    if (!banner.length) {
      banner = $(`<div id="focus-banner" style="display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; background:var(--marine-pale); border:1px solid var(--marine); border-radius:6px; padding:10px 14px; margin-bottom:12px;"></div>`);
      $('.tableau').before(banner);
    }
    const infoTitre = donnees[focusTicker] ? ` — ${esc(donnees[focusTicker].nom)}` : '';
    banner.html(`
      <span>
        <i class="fa-solid fa-crosshairs" style="color:var(--marine); margin-right:6px;"></i>
        Titre isolé : <strong>${esc(focusTicker)}</strong>${infoTitre}
        <span class="discret" style="font-size:0.85rem; margin-left:6px;">(scores calculés sur l'ensemble de ${esc(CFG.indice)})</span>
      </span>
      <button type="button" id="btn-clear-focus" class="lien-bouton">Afficher tout l'indice</button>
    `);
  }

  function tenterOuvrirFocus() {
    if (!focusTicker || focusAutoOuvert) return;
    const r = donnees[focusTicker];
    const rowObj = lignes[focusTicker];
    if (!r || !rowObj) return;
    const tr = rowObj.node();
    if (!tr) return;
    if (!rowObj.child.isShown()) {
      rowObj.child(detailHtml(r), 'detail-ligne').show();
      $(tr).addClass('ouvert');
    }
    focusAutoOuvert = true;
    majBanniereFocus();
  }

  function focaliserTicker(tk) {
    focusTicker = (tk || '').trim().toUpperCase();
    focusAutoOuvert = false;
    try {
      const u = new URL(window.location.href);
      if (focusTicker) u.searchParams.set('focus', focusTicker);
      else u.searchParams.delete('focus');
      window.history.replaceState(null, '', u.toString());
    } catch (e) {}
    majBanniereFocus();
    table.draw();
    majResume();
    tenterOuvrirFocus();
  }

  $(document).on('click', '#btn-clear-focus', function () {
    focaliserTicker('');
  });

  majBanniereFocus();

  /* ---------- Filtres DataTables ---------- */
  const nombre = id => {
    const el = $(id);
    if (!el.length) return null;
    const v = parseFloat(el.val());
    return Number.isNaN(v) ? null : v;
  };

  $.fn.dataTable.ext.search.push(function (settings, data, idx) {
    if (settings.nTable.id !== 'tbl') return true;
    const r = table.row(idx).data();
    if (!r) return true;

    if (focusTicker) {
      return (r.ticker || '').toUpperCase() === focusTicker;
    }

    const cont = $('#f-continent').val();
    if (cont && r.continent !== cont) return false;

    const dev = $('#f-devise').val();
    if (dev && r.devise !== dev) return false;

    const sect = $('#f-secteur').val(), sig = $('#f-signal').val();
    if (sect && r.secteur !== sect) return false;
    if (sig && !(r.signal || '').startsWith(sig)) return false;

    const favFiltre = $('#f-fav').val();
    if (favFiltre) {
      const lst = listesDuTicker(r.ticker);
      if (favFiltre === '__ANY__' || favFiltre === 'oui') {
        if (!lst.length) return false;
      } else if (!lst.includes(favFiltre)) {
        return false;
      }
    }

    if ($('#f-altman').val() === 'sain' && r.altman_zone === 'détresse') return false;
    const pio = r.piotroski_n ? r.piotroski / r.piotroski_n * 9 : null;
    const regles = [
      [nombre('#f-cap-min'), r.cap_usd_md, 'min'],
      [nombre('#f-cap-max'), r.cap_usd_md, 'max'],
      [nombre('#f-score'), r.score, 'min'],
      [nombre('#f-per'), r.per, 'max'],
      [nombre('#f-roic'), r.roic, 'min'],
      [nombre('#f-marge'), r.marge_secu, 'min'],
      [nombre('#f-pio'), pio, 'min'],
      [nombre('#f-div'), r.div_yield, 'min']
    ];
    for (const [seuil, v, sens] of regles) {
      if (seuil === null) continue;
      if (vide(v)) return false;
      if (sens === 'min' ? v < seuil : v > seuil) return false;
    }
    return true;
  });

  const MAP_FILTRES = {
    continent: '#f-continent', devise: '#f-devise', cap_min: '#f-cap-min', cap_max: '#f-cap-max',
    secteur: '#f-secteur', signal: '#f-signal', fav: '#f-fav', altman: '#f-altman',
    score: '#f-score', per: '#f-per', roic: '#f-roic', marge: '#f-marge', pio: '#f-pio', div: '#f-div'
  };

  function sauverFiltres() {
    if (!window.Reglages) return;
    const etat = {};
    Object.entries(MAP_FILTRES).forEach(([cle, sel]) => {
      if ($(sel).length) etat[cle] = String($(sel).val() || '');
    });
    window.Reglages.set('filtres_tableau', etat);
  }

  function restaurerFiltres() {
    if (!window.Reglages) return;
    const f = window.Reglages.lire('filtres_tableau') || {};
    Object.entries(MAP_FILTRES).forEach(([cle, sel]) => {
      if ($(sel).length && f[cle] !== undefined && f[cle] !== null) $(sel).val(f[cle]);
    });
    table.draw();
  }

  restaurerFiltres();
  if (window.Reglages) {
    window.Reglages.onChange(chemin => { if (chemin === '*') restaurerFiltres(); });
  }

  $('.filtres input, .filtres select').on('input change', () => {
    if (focusTicker) {
      focusTicker = '';
      majBanniereFocus();
    }
    $('.presets button').attr('aria-pressed', 'false');
    sauverFiltres();
    table.draw();
    majResume();
  });

  const PRESETS = {
    decote: { '#f-marge': 15, '#f-per': 15, '#f-score': 60 },
    qualite: { '#f-roic': 12, '#f-pio': 6, '#f-score': 60 },
    dividende: { '#f-div': 3.5, '#f-pio': 5, '#f-altman': 'sain' },
    solidite: { '#f-pio': 7, '#f-altman': 'sain', '#f-score': 50 },
    reset: {}
  };
  $('.presets button').on('click', function () {
    if (focusTicker) {
      focusTicker = '';
      majBanniereFocus();
    }
    $('.filtres input').val(''); $('.filtres select').val('');
    Object.entries(PRESETS[this.dataset.preset] || {}).forEach(([sel, v]) => $(sel).val(v));
    $('.presets button').attr('aria-pressed', 'false');
    if (this.dataset.preset !== 'reset') $(this).attr('aria-pressed', 'true');
    sauverFiltres();
    table.draw();
    majResume();
  });

  /* ---------- Menu multi-listes sur l'étoile (Watchlists) ---------- */
  function fermerMenuWatchlist() {
    $('#tq-wl-popover').remove();
  }

  function envoyerActionWatchlist(payload) {
    return fetch('/api/user/watchlists', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d && Array.isArray(d.lists) && d.items) {
          watchlists = { lists: d.lists, items: d.items };
          sauverWatchlistsLocal();
          synchroniserSelectWatchlists();
          rafraichirEtoiles();
          if ($('#f-fav').val()) table.draw(false);
        }
      })
      .catch(err => console.error('Erreur sauvegarde watchlist:', err));
  }

  function basculerListeTicker(tk, listName) {
    const actuelles = listesDuTicker(tk);
    if (actuelles.includes(listName)) {
      watchlists.items[tk] = actuelles.filter(x => x !== listName);
      if (!watchlists.items[tk].length) delete watchlists.items[tk];
    } else {
      watchlists.items[tk] = [...actuelles, listName];
    }
    sauverWatchlistsLocal();
    rafraichirEtoiles();
    if ($('#f-fav').val()) table.draw(false);
    envoyerActionWatchlist({ action: 'toggle', list_name: listName, ticker: tk });
  }

  function ouvrirMenuWatchlist(el) {
    const tk = el.dataset.ticker;
    const dejaOuvert = $('#tq-wl-popover');
    if (dejaOuvert.length && dejaOuvert.data('ticker') === tk) {
      fermerMenuWatchlist();
      return;
    }
    fermerMenuWatchlist();

    const actives = listesDuTicker(tk);
    const itemsHtml = watchlists.lists.map(nom => {
      const coche = actives.includes(nom) ? 'checked' : '';
      const nbDansListe = Object.values(watchlists.items).filter(arr => Array.isArray(arr) && arr.includes(nom)).length;
      return `
        <label style="display:flex; align-items:center; justify-content:space-between; gap:10px; padding:6px 8px; border-radius:4px; cursor:pointer; font-size:0.86rem; color:var(--encre);">
          <span style="display:flex; align-items:center; gap:8px;">
            <input type="checkbox" class="tq-wl-chk" data-list="${esc(nom)}" ${coche} style="accent-color:var(--marine); cursor:pointer;">
            <span>${esc(nom)}</span>
          </span>
          <small class="discret">${nbDansListe}</small>
        </label>
      `;
    }).join('');

    const pop = $(`
      <div id="tq-wl-popover" data-ticker="${esc(tk)}" role="dialog" aria-label="Listes de suivi pour ${esc(tk)}"
           style="position:fixed; z-index:9998; width:250px; background:var(--surface); color:var(--encre); border:1px solid var(--trait); border-radius:6px; box-shadow:0 10px 28px rgba(0,0,0,0.35); padding:10px;">
        <div style="display:flex; align-items:center; justify-content:space-between; padding-bottom:6px; margin-bottom:6px; border-bottom:1px solid var(--trait);">
          <strong style="font-size:0.85rem;">Listes · ${esc(tk)}</strong>
          <button type="button" id="tq-wl-close" style="background:none; border:none; color:var(--muted); cursor:pointer; font-size:1rem; line-height:1;" aria-label="Fermer">×</button>
        </div>
        <div class="tq-wl-items" style="display:flex; flex-direction:column; gap:2px; max-height:190px; overflow-y:auto;">
          ${itemsHtml}
        </div>
        <form id="tq-wl-new-form" style="display:flex; gap:6px; margin-top:8px; padding-top:8px; border-top:1px solid var(--trait);">
          <input type="text" id="tq-wl-new-input" placeholder="Nouvelle liste…" maxlength="40"
                 style="flex:1; min-width:0; font:inherit; font-size:0.82rem; padding:4px 7px; border:1px solid var(--trait); border-radius:4px; background:var(--papier); color:var(--encre);">
          <button type="submit" class="lien-bouton" style="padding:4px 9px; font-size:0.82rem;">+</button>
        </form>
      </div>
    `);

    $('body').append(pop);

    const rect = el.getBoundingClientRect();
    const popW = 250;
    const popH = pop.outerHeight() || 230;
    let left = rect.left;
    let top = rect.bottom + 6;
    if (left + popW > window.innerWidth - 12) left = Math.max(12, window.innerWidth - popW - 12);
    if (top + popH > window.innerHeight - 12) top = Math.max(12, rect.top - popH - 6);
    pop.css({ left: `${left}px`, top: `${top}px` });

    pop.on('click', e => e.stopPropagation());
    pop.find('#tq-wl-close').on('click', fermerMenuWatchlist);
    pop.find('.tq-wl-chk').on('change', function () {
      basculerListeTicker(tk, this.dataset.list);
    });
    pop.find('#tq-wl-new-form').on('submit', function (e) {
      e.preventDefault();
      const nouvelle = ($('#tq-wl-new-input').val() || '').trim();
      if (!nouvelle) return;
      if (!watchlists.lists.includes(nouvelle)) watchlists.lists.push(nouvelle);
      const actuelles = listesDuTicker(tk);
      if (!actuelles.includes(nouvelle)) watchlists.items[tk] = [...actuelles, nouvelle];
      sauverWatchlistsLocal();
      synchroniserSelectWatchlists();
      rafraichirEtoiles();
      envoyerActionWatchlist({ action: 'create_list', list_name: nouvelle, ticker: tk });
      fermerMenuWatchlist();
    });
  }

  $('#tbl tbody').on('click', '.etoile', function (e) {
    e.stopPropagation();
    ouvrirMenuWatchlist(this);
  });
  $('#tbl tbody').on('keydown', '.etoile', function (e) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      e.stopPropagation();
      ouvrirMenuWatchlist(this);
    }
  });
  $(document).on('click', function (e) {
    if (!$(e.target).closest('#tq-wl-popover, .etoile').length) {
      fermerMenuWatchlist();
    }
  });
  $(document).on('keydown', function (e) {
    if (e.key === 'Escape') fermerMenuWatchlist();
  });

  /* ---------- Détail dépliable d'une action ---------- */
  function detailHtml(r) {
    const alertes = [].concat(r.alertes || [], r.alertes_score || []);
    const fourch = (!vide(r.valo_bear) && !vide(r.valo_bull)) ? ` <small>(${fmt(r.valo_bear, 2)} – ${fmt(r.valo_bull, 2)})</small>` : '';
    const pot = vide(r.pot_graham) ? ND : `<span class="${classeSigne(r.pot_graham)}">${fmt(r.pot_graham, 0, ' %')}</span>`;
    const zone = r.altman_zone ? ` <small>(${esc(r.altman_zone)})</small>` : '';
    const pio = r.piotroski_n ? `${r.piotroski}/${r.piotroski_n}` : ND;
    const beta = vide(r.beta) ? ND : `${fmt(r.beta, 2)} <small>${r.beta_local ? 'indice local' : 'Yahoo'}</small>`;
    const gImp = (!vide(r.g_implicite) && !vide(r.g_retenue))
      ? `<span class="${r.g_implicite > r.g_retenue + 5 ? 'neg' : ''}">${fmt(r.g_implicite, 1, ' %')}</span> <small>vs ${fmt(r.g_retenue, 1, ' %')} retenue</small>` : ND;
    return `<div class="detail">
      <div class="detail-grille">
        <section><h4>Valorisation</h4><dl>
          ${dl('Valeur estimée' + (r.methode_valo ? ' (' + esc(r.methode_valo) + ')' : ''), vide(r.valo_base) ? ND : fmt(r.valo_base, 2) + fourch, 'Scénario central')}
          ${dl('Croissance que le cours suppose', gImp, 'DCF inversé')}
          ${dl('Poids de la valeur terminale', fmt(r.part_vt, 0, ' %'))}
          ${dl('Nombre de Graham (potentiel)', pot)}
          ${dl('PER', fmt(r.per, 1))}${dl('EV / EBITDA', fmt(r.ev_ebitda, 1))}
          ${dl('Rendement des bénéfices', fmt(r.earn_yield, 1, ' %'))}${dl('FCF yield', fmt(r.fcf_yield, 1, ' %'))}
          ${dl('Rendement du dividende', fmt(r.div_yield, 2, ' %'))}
        </dl></section>
        <section><h4>Rentabilité</h4><dl>
          ${dl('ROIC', fmt(r.roic, 1, ' %'))}
          ${dl('WACC', fmt(r.wacc, 1, ' %'))}${dl('Coût des fonds propres', fmt(r.ke, 1, ' %'))}
          ${dl('ROIC − WACC', `<span class="${classeSigne(r.spread)}">${fmt(r.spread, 1, ' pts')}</span>`)}
          ${dl('Marge opérationnelle', fmt(r.marge_op, 1, ' %'))}${dl('ROE', fmt(r.roe, 1, ' %'))}${dl('ROA', fmt(r.roa, 1, ' %'))}
        </dl></section>
        <section><h4>Solidité et croissance</h4><dl>
          ${dl('Dette nette / EBITDA', fmt(r.nd_ebitda, 1, ' x'))}
          ${dl('Dette / fonds propres', fmt(r.de, 0, ' %'))}
          ${dl('Altman Z', vide(r.altman) ? ND : fmt(r.altman, 2) + zone)}
          ${dl('Piotroski', pio)}
          ${dl('Croissance CA (3 ans)', fmt(r.cagr_ca, 1, ' %'))}${dl('Croissance FCF (3 ans)', fmt(r.cagr_fcf, 1, ' %'))}
        </dl></section>
        <section><h4>Risque et tendance</h4><dl>
          ${dl('Volatilité (1 an)', fmt(r.vol, 1, ' %'))}${dl('Baisse maximale (1 an)', fmt(r.mdd, 1, ' %'))}
          ${dl('Rendement (1 an)', fmt(r.rdt_1a, 1, ' %'))}${dl('Sharpe / Sortino', `${fmt(r.sharpe, 2)} / ${fmt(r.sortino, 2)}`)}
          ${dl('Bêta', beta)}
          ${dl('Écart à la MM200', fmt(r.dist_ma200, 1, ' %'))}${dl('Écart au plus haut 52 sem.', fmt(r.dist_52w, 1, ' %'))}
          ${dl('RSI (14)', fmt(r.rsi, 0))}
        </dl></section>
        <section><h4>Notation</h4><dl>
          ${dl('Valorisation / Qualité', `${fmt(r.valo, 0)} / ${fmt(r.qual, 0)}`)}${dl('Croissance / Risque', `${fmt(r.crois, 0)} / ${fmt(r.risq, 0)}`)}
          ${dl('Momentum', fmt(r.mom, 0))}${dl('Données disponibles', fmt(r.couverture, 0, ' %'))}
          ${r.macro ? dl('Contexte macro', esc(r.macro)) : ''}
        </dl></section>
      </div>
      ${alertes.length ? '<ul class="alertes">' + alertes.map(a => `<li>${esc(a)}</li>`).join('') + '</ul>' : ''}
      <p class="texte">${esc(r.resume)}</p>
      <div class="actions">
        <button type="button" class="lien-bouton" data-action="graph" data-ticker="${esc(r.ticker)}">Afficher le graphique</button>
        <button type="button" class="lien-bouton" data-action="actus" data-ticker="${esc(r.ticker)}">Voir les actualités</button>
        <a href="${esc(r.url)}" target="_blank" rel="noopener">Profil Yahoo Finance</a>
      </div>
      <div class="actus"></div>
      <div class="zone-graph">
        <div class="graph-periodes" style="display:none;" data-ticker="${esc(r.ticker)}">
          <button type="button" class="periode-btn" data-periode="1mo">1M</button>
          <button type="button" class="periode-btn" data-periode="3mo">3M</button>
          <button type="button" class="periode-btn" data-periode="6mo">6M</button>
          <button type="button" class="periode-btn actif" data-periode="1y">1A</button>
          <button type="button" class="periode-btn" data-periode="5y">5A</button>
          <button type="button" class="periode-btn" data-periode="max">Max</button>
        </div>
        <div class="graph-loading" style="display:none; padding:18px 0; color:var(--muted); font-size:.88rem;">Chargement du graphique...</div>
        <div class="graph-frame"></div>
      </div>
    </div>`;
  }

  $('#tbl tbody').on('click', 'tr', function (e) {
    if ($(e.target).closest('.etoile, a, button').length) return;
    const row = table.row(this);
    const r = row.data();
    if (!r) return;
    if (row.child.isShown()) { row.child.hide(); $(this).removeClass('ouvert'); }
    else { row.child(detailHtml(r), 'detail-ligne').show(); $(this).addClass('ouvert'); }
  });

  function chargerGraphiqueIframe(container, tk, periode) {
    const frame = container.find('.graph-frame');
    const loading = container.find('.graph-loading');
    loading.text('Chargement du graphique...').show();
    frame.empty();

    const theme = window.Theme ? window.Theme.get() : 'dark';
    const iframe = document.createElement('iframe');
    iframe.title = `Graphique ${esc(tk)} (${periode})`;
    iframe.loading = 'lazy';
    iframe.src = `/graph/${encodeURIComponent(tk)}?periode=${encodeURIComponent(periode)}#${theme}`;

    iframe.addEventListener('load', function () { loading.hide(); });
    iframe.addEventListener('error', function () {
      loading.html('<span style="color:var(--rouge);">Impossible de charger le graphique pour cette période.</span>');
    });

    frame.append(iframe);
  }

  $('#tbl tbody').on('click', '.periode-btn', function (e) {
    e.stopPropagation();
    const btn = $(this);
    const container = btn.closest('.zone-graph');
    const tk = btn.closest('.graph-periodes').data('ticker');
    const periode = btn.data('periode');
    btn.siblings('.periode-btn').removeClass('actif');
    btn.addClass('actif');
    chargerGraphiqueIframe(container, tk, periode);
  });

  $('#tbl tbody').on('click', 'button[data-action]', function () {
    const tk = this.dataset.ticker, zone = $(this).closest('.detail');
    if (this.dataset.action === 'graph') {
      const container = zone.find('.zone-graph');
      container.find('.graph-periodes').show();
      container.find('.periode-btn').removeClass('actif');
      container.find('.periode-btn[data-periode="1y"]').addClass('actif');
      chargerGraphiqueIframe(container, tk, '1y');
    } else {
      const cible = zone.find('.actus').text('Chargement…');
      fetch(`/api/detail/${encodeURIComponent(tk)}`).then(r => r.json()).then(d => {
        const note = vide(d.score) ? '' : ` <small>(polarité ${fmt(d.score, 2)}, indicatif)</small>`;
        cible.html(`Sentiment des derniers titres : <strong>${esc(d.etiquette)}</strong>${note}`
          + (d.titres.length ? '<ul>' + d.titres.map(t => `<li>${esc(t)}</li>`).join('') + '</ul>' : ''));
      }).catch(() => cible.text('Actualités indisponibles.'));
    }
  });

  function majResume() {
    const L = Object.values(donnees);
    if (!L.length) return;
    const cand = L.filter(r => (r.signal || '').startsWith('ACHAT')).length;
    const marges = L.map(r => r.marge_secu).filter(v => !vide(v)).sort((a, b) => a - b);
    const med = marges.length ? marges[Math.floor(marges.length / 2)] : null;
    const visibles = table.rows({ filter: 'applied' }).count();
    const noteFiltre = visibles < L.length ? ` <strong>(${visibles} visibles avec vos filtres actuels)</strong>` : '';
    $('#resume').html(`<strong>${L.length}</strong> titres en cache${total ? ' sur ' + total : ''}, dont <strong>${cand}</strong> candidats à l'achat. `
      + `Marge de sécurité médiane : <strong>${fmt(med, 1, ' %')}</strong>.${noteFiltre}`);
  }

  let minuterie = null;
  const redessiner = () => {
    if (minuterie) return;
    minuterie = setTimeout(() => {
      minuterie = null;
      if (document.activeElement && $(document.activeElement).closest('.dataTables_filter').length) return;
      table.draw(false);
      majResume();
      tenterOuvrirFocus();
    }, 100);
  };

  const reglages = window.Reglages ? encodeURIComponent(JSON.stringify(window.Reglages.serveur())) : '';
  const url = `/stream?indice=${encodeURIComponent(CFG.indice)}&secteur=${encodeURIComponent(CFG.secteur)}&r=${reglages}`;
  const src = new EventSource(url);

  src.addEventListener('init', e => {
    try {
      const info = JSON.parse(e.data);
      total = info.total;
      $('#etat').text(`Chargement depuis le cache (${info.en_cache || 0} / ${total} titres)…`);
    } catch (err) {}
  });

  src.addEventListener('statut', e => {
    try {
      const msg = JSON.parse(e.data).msg;
      if (msg) $('#etat').text(msg);
    } catch (err) {}
  });

  src.onmessage = e => {
    try {
      const r = JSON.parse(e.data);
      if (!r || !r.ticker) return;
      donnees[r.ticker] = r;
      if (r.devise && !devisesVues.has(r.devise) && $('#f-devise').length) {
        devisesVues.add(r.devise);
        $('#f-devise').append(`<option value="${esc(r.devise)}">${esc(r.devise)}</option>`);
      }
      if (lignes[r.ticker]) {
        lignes[r.ticker].data(r);
      } else {
        lignes[r.ticker] = table.row.add(r);
      }
      if (focusTicker && r.ticker.toUpperCase() === focusTicker) {
        table.draw(false);
        tenterOuvrirFocus();
      } else {
        redessiner();
      }
    } catch (err) {}
  };

  src.addEventListener('progress', e => {
    try {
      const p = JSON.parse(e.data);
      const recus = p.recus !== undefined ? p.recus : Object.keys(donnees).length;
      $('#barre').attr('value', total ? recus / total : 0);
      $('#etat').text(`${recus} / ${total} titres chargés depuis le cache`);
    } catch (err) {}
  });

  src.addEventListener('scores', e => {
    try {
      const sc = JSON.parse(e.data);
      Object.keys(sc).forEach(tk => {
        if (donnees[tk]) {
          Object.assign(donnees[tk], sc[tk]);
          lignes[tk].data(donnees[tk]);
        }
      });
      if (focusTicker && donnees[focusTicker] && lignes[focusTicker]?.child.isShown()) {
        lignes[focusTicker].child(detailHtml(donnees[focusTicker]), 'detail-ligne').show();
      }
      redessiner();
    } catch (err) {}
  });

  src.addEventListener('close', () => {
    termine = true;
    src.close();
    $('#barre').attr('value', 1);
    const nbRecus = Object.keys(donnees).length;
    if (nbRecus === 0) {
      $('#etat').html('<span style="color:var(--rouge);">Aucune donnée en cache pour cet indice. Lancez un chargement depuis l\'interface Admin.</span>');
    } else {
      $('#etat').text(`Données chargées depuis le cache (${nbRecus} / ${total} titres).`);
    }
    table.draw(false);
    majResume();
    tenterOuvrirFocus();
  });

  src.onerror = () => {
    if (termine) return;
    src.close();
    $('#etat').text('Connexion interrompue : rechargez la page.');
  };

  // ---------- Colonne latérale droite : Contexte de marché en direct ----------
  const macroListes = {
    macro: document.getElementById('macro-list-macro'),
    energie: document.getElementById('macro-list-energie'),
    materiaux: document.getElementById('macro-list-materiaux'),
    secteurs: document.getElementById('macro-list-secteurs'),
  };
  const btnMajMacro = document.getElementById('btn-maj-macro');
  const inputFiltreMacro = document.getElementById('macro-filter');

  function normaliserTexteMacro(txt) {
    return String(txt || '')
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '');
  }

  function formaterNombreFr(val, dec) {
    if (val === null || val === undefined || !Number.isFinite(Number(val))) return '—';
    return Number(val).toLocaleString('fr-FR', {
      minimumFractionDigits: dec,
      maximumFractionDigits: dec,
    });
  }

  function appliquerFiltreMacro() {
    if (!inputFiltreMacro) return;
    const terme = normaliserTexteMacro(inputFiltreMacro.value.trim());
    document.querySelectorAll('.macro-groupe').forEach(section => {
      let visibles = 0;
      section.querySelectorAll('.macro-item').forEach(li => {
        const cible = li.dataset.recherche || '';
        const ok = !terme || cible.includes(terme);
        li.style.display = ok ? '' : 'none';
        if (ok) visibles += 1;
      });
      section.style.display = visibles > 0 || !terme ? '' : 'none';
    });
  }

  async function chargerContexteMacro() {
    if (!macroListes.macro) return;
    if (btnMajMacro) btnMajMacro.disabled = true;
    try {
      const resp = await fetch('/api/macro', { cache: 'no-store' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const items = Array.isArray(data && data.items) ? data.items : [];

      Object.values(macroListes).forEach(ul => {
        if (ul) ul.innerHTML = '';
      });

      items.forEach(item => {
        const ul = macroListes[item.groupe];
        if (!ul) return;

        const dec = Number.isInteger(item.dec) ? item.dec : 1;
        const unite = item.unite || '';
        const prixTxt = item.prix !== null && item.prix !== undefined && Number.isFinite(Number(item.prix))
          ? `${formaterNombreFr(item.prix, dec)}${unite}`
          : '—';

        let varTxt = '—';
        let varCls = '';
        if (item.var_1m !== null && item.var_1m !== undefined && Number.isFinite(Number(item.var_1m))) {
          const v = Number(item.var_1m);
          const signe = v > 0 ? '+' : '';
          varTxt = `${signe}${formaterNombreFr(v, 1)} %`;
          if (v > 0) varCls = 'pos';
          else if (v < 0) varCls = 'neg';
        }

        const li = document.createElement('li');
        li.className = 'macro-item';
        li.dataset.recherche = normaliserTexteMacro(`${item.nom || ''} ${item.ticker || ''}`);
        li.title = `${item.nom || ''} (${item.ticker || ''}) — Variation sur 1 mois`;
        li.innerHTML = `<span class="macro-item-nom">${esc(item.nom || item.ticker)}</span>`
          + `<span class="macro-item-val"><span class="macro-prix">${esc(prixTxt)}</span>`
          + `<span class="macro-var ${varCls}">${esc(varTxt)}</span></span>`;
        ul.appendChild(li);
      });

      appliquerFiltreMacro();
    } catch (err) {
      Object.values(macroListes).forEach(ul => {
        if (ul && !ul.children.length) {
          ul.innerHTML = '<li class="macro-vide">Cours indisponibles</li>';
        }
      });
    } finally {
      if (btnMajMacro) btnMajMacro.disabled = false;
    }
  }

  if (btnMajMacro) {
    btnMajMacro.addEventListener('click', chargerContexteMacro);
  }
  if (inputFiltreMacro) {
    inputFiltreMacro.addEventListener('input', appliquerFiltreMacro);
  }
  chargerContexteMacro();

  Object.assign(window.Quant, { src, majResume, focaliserTicker, chargerContexteMacro });
});