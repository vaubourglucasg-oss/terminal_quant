/* dashboard.js - Tableau de bord complet */
window.Quant = window.Quant || {};

$(function () {
  const CFG = window.CFG;
  let favoris = {};
  try { favoris = JSON.parse(localStorage.getItem('quant_favoris') || '{}'); } catch (e) { favoris = {}; }

  const donnees = {};
  const lignes = {};
  let total = 0, termine = false;

  // ---------- utilitaires ----------
  const ND = '<span class="nd">–</span>';
  const vide = v => v === null || v === undefined || Number.isNaN(v);
  const fmt = (v, d = 1, suf = '') => vide(v) ? ND : v.toFixed(d).replace('.', ',') + suf;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const SECTEURS_FR = { 'Technology': 'Technologie', 'Healthcare': 'Santé', 'Financial Services': 'Finance',
    'Consumer Cyclical': 'Conso. cyclique', 'Consumer Defensive': 'Conso. défensive', 'Industrials': 'Industrie',
    'Energy': 'Énergie', 'Basic Materials': 'Matériaux', 'Utilities': 'Services publics',
    'Real Estate': 'Immobilier', 'Communication Services': 'Communication' };
  const classeSigne = v => vide(v) ? '' : (v > 0 ? 'pos' : (v < 0 ? 'neg' : ''));

  // Exposer immédiatement pour le comparateur
  Object.assign(window.Quant, { donnees, esc, fmt, vide, SECTEURS_FR });

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

  // ---------- COLONNES ----------
  const COLONNES = [
    { data: null, orderable: false, className: 't-g', title: '', width: '52px',
      render: (d, type, r) => type === 'display'
        ? `<i class="etoile ${favoris[r.ticker] ? 'actif' : ''}" data-ticker="${esc(r.ticker)}" role="button" tabindex="0" aria-label="Ajouter aux favoris" title="Favori">★</i>`
        + `<button type="button" class="cmp ${(window.Quant && window.Quant.cmpSel || []).includes(r.ticker) ? 'actif' : ''}" data-ticker="${esc(r.ticker)}" title="Ajouter au comparateur" aria-label="Comparer ${esc(r.ticker)}">⇄</button>`
        : (favoris[r.ticker] ? 1 : 0) },
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
  ];

  const COLS_EXPORT = [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14];

  // ---------- tableau ----------
  const table = $('#tbl').DataTable({
    data: [], columns: COLONNES, pageLength: 100, order: [[4, 'desc']], autoWidth: false, dom: 'Bfrtip',
    buttons: [
      { extend: 'csv', text: 'Exporter en CSV', exportOptions: { orthogonal: 'export', columns: COLS_EXPORT } },
      { extend: 'excel', text: 'Exporter en Excel', exportOptions: { orthogonal: 'export', columns: COLS_EXPORT } }
    ],
    language: { search: 'Rechercher :', lengthMenu: '_MENU_ lignes', info: '_TOTAL_ titres affichés', infoEmpty: 'Aucun titre',
      infoFiltered: '(sur _MAX_)', emptyTable: 'Analyse en cours, les premiers titres arrivent…',
      zeroRecords: 'Aucun titre ne correspond aux filtres.', paginate: { previous: 'Précédent', next: 'Suivant' } }
  });
  
  window.Quant.table = table;

  // ---------- filtres ----------
  const nombre = id => { const v = parseFloat($(id).val()); return Number.isNaN(v) ? null : v; };
  $.fn.dataTable.ext.search.push(function (settings, data, idx) {
    if (settings.nTable.id !== 'tbl') return true;
    const r = table.row(idx).data();
    if (!r) return true;
    const sect = $('#f-secteur').val(), sig = $('#f-signal').val();
    if (sect && r.secteur !== sect) return false;
    if (sig && !(r.signal || '').startsWith(sig)) return false;
    if ($('#f-fav').val() === 'oui' && !favoris[r.ticker]) return false;
    if ($('#f-altman').val() === 'sain' && r.altman_zone === 'détresse') return false;
    const pio = r.piotroski_n ? r.piotroski / r.piotroski_n * 9 : null;
    const regles = [[nombre('#f-score'), r.score, 'min'], [nombre('#f-per'), r.per, 'max'], [nombre('#f-roic'), r.roic, 'min'],
      [nombre('#f-marge'), r.marge_secu, 'min'], [nombre('#f-pio'), pio, 'min'], [nombre('#f-div'), r.div_yield, 'min']];
    for (const [seuil, v, sens] of regles) {
      if (seuil === null) continue;
      if (vide(v)) return false;
      if (sens === 'min' ? v < seuil : v > seuil) return false;
    }
    return true;
  });
  $('.filtres input, .filtres select').on('input change', () => { $('.presets button').attr('aria-pressed', 'false'); table.draw(); });

  const PRESETS = {
    decote: { '#f-marge': 15, '#f-per': 18, '#f-score': 55 },
    qualite: { '#f-roic': 12, '#f-pio': 6, '#f-score': 60 },
    dividende: { '#f-div': 3.5, '#f-pio': 5, '#f-altman': 'sain' },
    solidite: { '#f-pio': 7, '#f-altman': 'sain', '#f-score': 50 },
    reset: {}
  };
  $('.presets button').on('click', function () {
    $('.filtres input').val(''); $('.filtres select').val('');
    Object.entries(PRESETS[this.dataset.preset] || {}).forEach(([sel, v]) => $(sel).val(v));
    $('.presets button').attr('aria-pressed', 'false');
    if (this.dataset.preset !== 'reset') $(this).attr('aria-pressed', 'true');
    table.draw();
  });

  // ---------- favoris ----------
  function basculerFavori(el) {
    const tk = el.dataset.ticker;
    if (favoris[tk]) delete favoris[tk]; else favoris[tk] = true;
    try { localStorage.setItem('quant_favoris', JSON.stringify(favoris)); } catch (e) { }
    $(el).toggleClass('actif', !!favoris[tk]);
  }
  $('#tbl tbody').on('click', '.etoile', function (e) { e.stopPropagation(); basculerFavori(this); });
  $('#tbl tbody').on('keydown', '.etoile', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); basculerFavori(this); } });

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
      <div class="actus"></div><div class="zone-graph"></div>
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

  $('#tbl tbody').on('click', 'button[data-action]', function () {
    const tk = this.dataset.ticker, zone = $(this).closest('.detail');
    if (this.dataset.action === 'graph') {
      zone.find('.zone-graph').html(`<iframe src="/graph/${encodeURIComponent(tk)}#${window.Theme ? window.Theme.get() : 'dark'}" title="Graphique ${esc(tk)}" loading="lazy"></iframe>`);
    } else {
      const cible = zone.find('.actus').text('Chargement…');
      fetch(`/api/detail/${encodeURIComponent(tk)}`).then(r => r.json()).then(d => {
        const note = vide(d.score) ? '' : ` <small>(polarité ${fmt(d.score, 2)}, indicatif)</small>`;
        cible.html(`Sentiment des derniers titres : <strong>${esc(d.etiquette)}</strong>${note}`
          + (d.titres.length ? '<ul>' + d.titres.map(t => `<li>${esc(t)}</li>`).join('') + '</ul>' : ''));
      }).catch(() => cible.text('Actualités indisponibles.'));
    }
  });

  // ---------- résumé et avancement ----------
  function majResume() {
    const L = Object.values(donnees);
    if (!L.length) return;
    const cand = L.filter(r => (r.signal || '').startsWith('ACHAT')).length;
    const marges = L.map(r => r.marge_secu).filter(v => !vide(v)).sort((a, b) => a - b);
    const med = marges.length ? marges[Math.floor(marges.length / 2)] : null;
    $('#resume').html(`<strong>${L.length}</strong> titres analysés${total ? ' sur ' + total : ''}, dont <strong>${cand}</strong> candidats à l'achat. `
      + `Marge de sécurité médiane : <strong>${fmt(med, 1, ' %')}</strong>.`
      + (termine ? '' : ' <span class="discret">Classement provisoire tant que l\'analyse n\'est pas terminée.</span>'));
  }

  let minuterie = null;
  const redessiner = () => { 
    if (minuterie) return; 
    minuterie = setTimeout(() => { 
      minuterie = null; 
      if (document.activeElement && $(document.activeElement).closest('.dataTables_filter').length) return; 
      table.draw(false); 
      majResume(); 
    }, 250); 
  };

  // ---------- flux temps réel (SSE) ----------
  console.log("Tentative de connexion SSE vers:", CFG.indice);
  const reglages = window.Reglages ? encodeURIComponent(JSON.stringify(window.Reglages.serveur())) : '';
  const url = `/stream?indice=${encodeURIComponent(CFG.indice)}&secteur=${encodeURIComponent(CFG.secteur)}&r=${reglages}`;
  const src = new EventSource(url);
  
  src.addEventListener('init', e => { 
    console.log("Flux initié par le serveur !");
    total = JSON.parse(e.data).total; 
    $('#etat').text(`Analyse de ${total} titres…`); 
  });
  
  src.onmessage = e => {
    const r = JSON.parse(e.data);
    donnees[r.ticker] = r;
    lignes[r.ticker] = table.row.add(r);
    redessiner();
  };
  
  src.addEventListener('progress', e => {
    const fait = JSON.parse(e.data).done;
    $('#barre').attr('value', total ? fait / total : 0);
    $('#etat').text(`${fait} / ${total} titres traités`);
  });
  
  src.addEventListener('scores', e => {
    const sc = JSON.parse(e.data);
    Object.keys(sc).forEach(tk => { if (donnees[tk]) { Object.assign(donnees[tk], sc[tk]); lignes[tk].data(donnees[tk]); } });
    redessiner();
  });
  
  src.addEventListener('close', () => {
    console.log("Analyse terminée avec succès.");
    termine = true; src.close();
    $('#barre').attr('value', 1);
    $('#etat').text('Analyse terminée.');
    table.draw(false); majResume();
  });
  
  src.onerror = (e) => {
    console.error("Erreur de connexion au flux SSE (Le backend a coupé la connexion)", e);
    if (termine) return;
    src.close();
    $('#etat').text('Connexion interrompue : rechargez la page ou redémarrez le serveur Python.');
  };

  // Exposé pour parametres.js (recalcul du classement, attente de la fin de l'analyse)
  Object.assign(window.Quant, { src, majResume });
});
