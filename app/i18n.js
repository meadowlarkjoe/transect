/* Transect — i18n.
   EN/FR. French is not decoration here: the data, the regulations and the guiding
   convention (Cartes Xperts) are all French, and the intended user is a Québec hunter.
   t('key') returns the active string; t('key','fallback') is safe for keys not yet
   translated — it returns the fallback rather than printing the key at the user. */
(function (global) {
  const DICT = {
    en: {
  'base.overzoom':'Past the sharpest imagery published here — the last real tile is being stretched, not lost.',
  'setup.party':'Hunters in the party',
  'setup.partyU':'hunters',
  'setup.partyNote':'Party size changes the analysis, not just the wording: focus areas are sized to hold the crew, and each area gets a calling stand per hunter plus glassing positions to pair up on.',
  'crew.title':'CREW PLAN',
  'crew.holds':'this area holds',
  'crew.of':'of',
  'pill.cap':'HUNT MAP',
  'pill.name':'Layers',
  'lay.on':'ON',
  'rail.tools':'TOOLS',
  'tip.measuring':'MEASURING',
  'tip.esc':'ESC TO EXIT',
  'tip.assume':'Estimated at 2.5 km/h bushwhack. A loaded pack-out is roughly half that.',
  'tip.areaAssume':'Spherical area of the ring as drawn.',
  'ctl.north':'North up',
  'ctl.in':'Zoom in',
  'ctl.out':'Zoom out',
  'ctl.base':'Basemap',
  'ctl.locate':'Centre the area',
  'surf.title':'Model surface',
  'surf.show':'Show huntability',
  'surf.ramp':'VALUE RAMP',
  'surf.banded':'Banded',
  'surf.cont':'Continuous',
  'surf.hide':'Hide below',
  'surf.op':'Opacity',
  'surf.none':'none',
  'surf.holes':'Holes in the surface are <b>excluded</b> ground — deep water, road corridors, outfitter tenure — not low scores. Excluded is not the same as bad, and the model refuses to guess there.',
  'stats.cap':'AREA STATISTICS',
  'stats.conf':'CONFIDENCE',
  'stats.none':'Outside a ranked area — the model scores the raster here but did not cluster it into a focus area.',
      // ---- chrome ----
      'tab.setup': 'Setup', 'tab.overview': 'Overview', 'tab.field': 'Field', 'tab.brief': 'Brief',
      'nav.plans': 'Plans', 'nav.export': 'Export', 'nav.account': 'Account',
      'nav.signin': 'Sign in', 'nav.signout': 'Sign out', 'nav.yourplans': 'Your hunt plans',
      'state.saved': 'SAVED', 'state.unsaved': 'UNSAVED',
      'tab.locked': 'Run an analysis first — there is nothing to show yet',

      // ---- setup ----
      'setup.title': 'Scout setup',
      'setup.lede': 'Define the box and the hunter. Both filter every recommendation downstream.',
      'setup.s1': 'Where & when', 'setup.s2': 'Quarry & extent', 'setup.s3': 'Hunter profile',
      'setup.search': 'Search a place', 'setup.searchph': 'Search a place, lake, mine…',
      'setup.searchbtn': 'Search', 'setup.dragbox': '▛ Drag a box on the map',
      'setup.coords': 'Or paste coordinates',
      'setup.dates': 'Hunt dates',
      'setup.datesnote': 'Drives rut timing, weather and behaviour. Peak breeding ≈ Oct 2 at this latitude — but bulls are most callable in the two weeks before it.',
      'setup.species': 'Species', 'setup.radius': 'Search radius',
      'setup.radiushint': '~20 km+ resolves focus areas',
      'setup.style': "How you'll hunt", 'setup.spike': 'Spike camp', 'setup.vehicle': 'Return to vehicle',
      'setup.watercraft': 'Watercraft', 'setup.noboat': 'No boat', 'setup.canoe': 'Canoe', 'setup.motor': 'Motorboat',
      'setup.wcnote': 'With no boat, rivers become foot barriers — ground across one from the road drops out of the ranking.',
      'setup.walkaccess': 'Walk: access → base camp (max)',
      'setup.walkhunt': 'Walk: base camp → hunting (max)',
      'setup.leaving': 'Leaving from', 'setup.leavingph': 'Search departure town…',
      'setup.units': 'Units', 'setup.metric': 'Metric', 'setup.imperial': 'Imperial',
      'setup.basemap': 'Basemap',
      'setup.run': 'RUN ANALYSIS →', 'setup.runnew': 'RUN NEW ANALYSIS →',
      'setup.runnote.title': 'Live recompute — 3–5 minutes',
      'setup.runnote.body': 'Downloads terrain, imagery, land-cover, burn history and hydrography for the box, then re-runs the model. Progress sits at 0% through the download stage; that’s normal.',
      'setup.replace.title': 'This replaces your current analysis',
      'setup.replace.body': 'The areas, zones and brief on screen now are for a different box. Running again discards them — save the current plan first if you want to keep it.',
      'setup.needdates.title': 'Set your hunt dates first',
      'setup.needdates.body': 'Hunt dates drive rut phase, weather and which behaviour the model weights — without them the result would be for dates you never chose.',
      'setup.locked.title': 'Nothing to show yet',
      'setup.locked.body': 'Overview, Field and Brief all describe a computed analysis. Set your area and dates, then run it — they unlock as soon as it finishes.',

      // ---- empty states ----
      'empty.title': 'Nothing on the map yet',
      'empty.body': 'Draw a box in Setup, set your hunt dates and who’s hunting, then run the analysis. It takes a few minutes and everything you see afterwards is computed for that box — not a sample.',
      'empty.cta': 'Set up a hunt →', 'empty.example': 'Or load the Fire Lake example',
      'empty.brief': 'A brief is written for a specific area, so there’s nothing to write until you’ve run an analysis.',
      'empty.briefhead': 'No brief yet',

      // ---- layers ----
      'lay.title': 'Hunting layers', 'lay.meaning': 'What each colour means',
      'lay.g.zones': 'Model zones', 'lay.g.sites': 'Sites & features', 'lay.g.access': 'Access & hydro',
      'lay.high': 'High likelihood', 'lay.high.n': 'Model score in the top band',
      'lay.med': 'Medium', 'lay.med.n': 'Scored, second band',
      'lay.low': 'Low', 'lay.low.n': 'Scored but not prioritised',
      'lay.refuge': 'Thermal refuge', 'lay.refuge.n': 'Cool midday bedding',
      'lay.browse': 'Browse / feeding', 'lay.browse.n': 'Regen & riparian forage — the food itself',
      'lay.burns': 'Burn regeneration', 'lay.burns.n': 'Mapped fire perimeters by age — browse peaks 15–22 yr after a burn. The single strongest predictor here.',
      'lay.funnel': 'Funnels / passes', 'lay.funnel.n': 'Terrain pinch points — inferred from the DEM, weakly evidenced',
      'lay.sites': 'Hunt sites', 'lay.sites.n': 'Calling, feeding, glassing, ground-truth',
      'lay.camps': 'Camps & staging', 'lay.camps.n': 'Where you sleep; where the truck sits',
      'lay.shooters': 'Caller / shooter', 'lay.shooters.n': 'Shooter ~70 m downwind of the caller',
      'lay.areas': 'Focus-area outlines', 'lay.areas.n': 'Plan extent',
      'lay.thermal': 'Thermal drift', 'lay.thermal.n': 'Modelled slope airflow — an inference, not a measurement',
      'lay.routes': 'Routes', 'lay.routes.n': 'Access in, and the best line to hunt',
      'lay.roads': 'Roads & rail', 'lay.roads.n': 'Reference geography, not a model output',
      'lay.tenure': 'Outfitter / tenure', 'lay.tenure.n': 'Pourvoiries, ZECs, réserves — hatched red is CLOSED to you and is masked out of the ranking',
      'lay.bounds': 'Borders & places', 'lay.bounds.n': 'Reference geography',
      'lay.water': 'Rivers & lakes', 'lay.water.n': 'Mapped hydrography (OSM)',
      'lay.cross': 'River crossings', 'lay.cross.n': 'Red = needs a boat · amber = fordable',
      'lay.nodata': 'NO DATA',

      // ---- basemap ----
      'base.title': 'Basemap', 'base.opacity': 'Opacity', 'base.terrain': 'Terrain',
      'base.3d': '3D terrain', 'base.exag': 'Exaggeration', 'base.more': 'Additional imagery',

      // ---- overview / brief ----
      'ov.diy': 'DIY POSSIBLE', 'ov.restricted': 'RESTRICTED',
      'ov.confirm': 'thing to confirm before you go', 'ov.confirms': 'things to confirm before you go',
      'ov.looking': "What I'm looking for",
      'ov.why': 'Why it scored', 'ov.working': 'Working for you', 'ov.watch': 'Watch-outs',
      'ov.allareas': '← all areas', 'ov.habitat': 'habitat', 'ov.packout': 'pack-out',
      'br.dates': 'Your dates & the rut', 'br.how': 'How to hunt it',
      'br.inout': 'Getting in & out', 'br.dayplan': 'Your day plan', 'br.better': 'How to do better',
      'br.factors': 'Weighted factors', 'br.sites': 'Sites',
      'br.valider': 'À valider sur le terrain.',
      'br.validerbody': 'Every mark below is a hypothesis to ground-truth on foot — the model reads habitat, not animals.',

      // ---- misc ----
      'w.pickday': 'Pick a day → sites turn green when the forecast wind fits their approach',
      'x.title': "Export this plan's waypoints, routes & areas:",
      'x.gpx': 'GPX — OnX / Garmin', 'x.kml': 'KML — Google Earth', 'x.zones': 'include model zones',
      'lang.label': 'Language'
    },

    fr: {
  'base.overzoom':'Au-delà de l’imagerie la plus nette ici — la dernière tuile réelle est étirée, pas perdue.',
  'setup.party':'Chasseurs dans le groupe',
  'setup.partyU':'chasseurs',
  'setup.partyNote':'La taille du groupe modifie l’analyse, pas seulement le texte : les secteurs sont dimensionnés pour accueillir l’équipe, et chacun reçoit un poste d’appel par chasseur plus des postes d’observation à jumeler.',
  'crew.title':'PLAN D’ÉQUIPE',
  'crew.holds':'ce secteur accueille',
  'crew.of':'de',
  'pill.cap':'CARTE DE CHASSE',
  'pill.name':'Couches',
  'lay.on':'ACTIVES',
  'rail.tools':'OUTILS',
  'tip.measuring':'MESURE EN COURS',
  'tip.esc':'ÉCHAP POUR QUITTER',
  'tip.assume':'Estimé à 2,5 km/h en forêt. Une sortie chargée prend environ le double.',
  'tip.areaAssume':'Aire sphérique du contour tel que tracé.',
  'ctl.north':'Nord en haut',
  'ctl.in':'Zoom avant',
  'ctl.out':'Zoom arrière',
  'ctl.base':'Fond de carte',
  'ctl.locate':'Recentrer le secteur',
  'surf.title':'Surface du modèle',
  'surf.show':'Afficher la chassabilité',
  'surf.ramp':'ÉCHELLE DE VALEURS',
  'surf.banded':'Par paliers',
  'surf.cont':'Continue',
  'surf.hide':'Masquer sous',
  'surf.op':'Opacité',
  'surf.none':'aucun',
  'surf.holes':'Les trous dans la surface sont des terrains <b>exclus</b> — eau profonde, emprises routières, territoires de pourvoirie — et non de faibles scores. Exclu n’est pas synonyme de mauvais : le modèle refuse d’y deviner.',
  'stats.cap':'STATISTIQUES DU SECTEUR',
  'stats.conf':'CONFIANCE',
  'stats.none':'Hors d’un secteur classé — le modèle évalue le raster ici mais ne l’a pas regroupé en secteur prioritaire.',
      'tab.setup': 'Paramètres', 'tab.overview': 'Aperçu', 'tab.field': 'Terrain', 'tab.brief': 'Sommaire',
      'nav.plans': 'Plans', 'nav.export': 'Exporter', 'nav.account': 'Compte',
      'nav.signin': 'Se connecter', 'nav.signout': 'Se déconnecter', 'nav.yourplans': 'Vos plans de chasse',
      'state.saved': 'ENREGISTRÉ', 'state.unsaved': 'NON ENREGISTRÉ',
      'tab.locked': 'Lancez d’abord une analyse — il n’y a rien à afficher',

      'setup.title': 'Configuration',
      'setup.lede': 'Définissez le secteur et le chasseur. Les deux filtrent toutes les recommandations en aval.',
      'setup.s1': 'Où et quand', 'setup.s2': 'Gibier et étendue', 'setup.s3': 'Profil du chasseur',
      'setup.search': 'Rechercher un lieu', 'setup.searchph': 'Lac, mine, municipalité…',
      'setup.searchbtn': 'Rechercher', 'setup.dragbox': '▛ Tracer un rectangle sur la carte',
      'setup.coords': 'Ou coller des coordonnées',
      'setup.dates': 'Dates de chasse',
      'setup.datesnote': 'Détermine le rut, la météo et le comportement. Le pic de reproduction ≈ 2 oct. à cette latitude — mais les mâles répondent le mieux à l’appel dans les deux semaines qui précèdent.',
      'setup.species': 'Espèce', 'setup.radius': 'Rayon de recherche',
      'setup.radiushint': '~20 km et plus pour dégager des secteurs',
      'setup.style': 'Type de chasse', 'setup.spike': 'Camp volant', 'setup.vehicle': 'Retour au véhicule',
      'setup.watercraft': 'Embarcation', 'setup.noboat': 'Aucune', 'setup.canoe': 'Canot', 'setup.motor': 'Chaloupe à moteur',
      'setup.wcnote': 'Sans embarcation, les rivières deviennent des barrières à pied — le terrain de l’autre côté est retiré du classement.',
      'setup.walkaccess': 'Marche : accès → camp de base (max)',
      'setup.walkhunt': 'Marche : camp de base → chasse (max)',
      'setup.leaving': 'Départ de', 'setup.leavingph': 'Municipalité de départ…',
      'setup.units': 'Unités', 'setup.metric': 'Métrique', 'setup.imperial': 'Impérial',
      'setup.basemap': 'Fond de carte',
      'setup.run': 'LANCER L’ANALYSE →', 'setup.runnew': 'NOUVELLE ANALYSE →',
      'setup.runnote.title': 'Calcul en direct — 3 à 5 minutes',
      'setup.runnote.body': 'Télécharge le relief, l’imagerie, la couverture du sol, l’historique des feux et l’hydrographie du secteur, puis relance le modèle. La progression reste à 0 % pendant le téléchargement; c’est normal.',
      'setup.replace.title': 'Ceci remplace votre analyse actuelle',
      'setup.replace.body': 'Les secteurs, zones et le sommaire à l’écran visent un autre rectangle. Relancer les efface — enregistrez le plan d’abord si vous voulez le garder.',
      'setup.needdates.title': 'Indiquez d’abord vos dates de chasse',
      'setup.needdates.body': 'Les dates déterminent la phase du rut, la météo et le comportement pondéré par le modèle — sans elles, le résultat viserait des dates que vous n’avez jamais choisies.',
      'setup.locked.title': 'Rien à afficher pour l’instant',
      'setup.locked.body': 'Aperçu, Terrain et Sommaire décrivent tous une analyse calculée. Définissez le secteur et les dates, puis lancez l’analyse — ils se débloquent dès qu’elle se termine.',

      'empty.title': 'Rien sur la carte pour l’instant',
      'empty.body': 'Tracez un rectangle dans Paramètres, indiquez vos dates et votre profil, puis lancez l’analyse. Cela prend quelques minutes et tout ce qui suit est calculé pour ce secteur — pas un exemple.',
      'empty.cta': 'Configurer une chasse →', 'empty.example': 'Ou charger l’exemple de Fire Lake',
      'empty.brief': 'Un sommaire est rédigé pour un secteur précis; il n’y a donc rien à écrire tant qu’une analyse n’a pas été lancée.',
      'empty.briefhead': 'Aucun sommaire',

      'lay.title': 'Couches de chasse', 'lay.meaning': 'Signification des couleurs',
      'lay.g.zones': 'Zones du modèle', 'lay.g.sites': 'Sites et éléments', 'lay.g.access': 'Accès et hydrographie',
      'lay.high': 'Probabilité élevée', 'lay.high.n': 'Score du modèle dans la tranche supérieure',
      'lay.med': 'Moyenne', 'lay.med.n': 'Deuxième tranche',
      'lay.low': 'Faible', 'lay.low.n': 'Coté mais non prioritaire',
      'lay.refuge': 'Refuge thermique', 'lay.refuge.n': 'Remise fraîche du midi',
      'lay.browse': 'Brout / alimentation', 'lay.browse.n': 'Régénération et brout riverain — la nourriture même',
      'lay.burns': 'Régénération après feu', 'lay.burns.n': 'Périmètres de feux par âge — le brout culmine 15 à 22 ans après le feu. Le meilleur prédicteur ici.',
      'lay.funnel': 'Corridors / cols', 'lay.funnel.n': 'Rétrécissements du relief — déduits du MNT, faiblement étayés',
      'lay.sites': 'Sites de chasse', 'lay.sites.n': 'Appel, alimentation, observation, validation',
      'lay.camps': 'Camps et stationnement', 'lay.camps.n': 'Où vous dormez; où le véhicule reste',
      'lay.shooters': 'Appelant / tireur', 'lay.shooters.n': 'Tireur à ~70 m sous le vent de l’appelant',
      'lay.areas': 'Contours des secteurs', 'lay.areas.n': 'Étendue du plan',
      'lay.thermal': 'Dérive thermique', 'lay.thermal.n': 'Écoulement d’air modélisé — une déduction, pas une mesure',
      'lay.routes': 'Trajets', 'lay.routes.n': 'L’accès, et la meilleure ligne de chasse',
      'lay.roads': 'Routes et voie ferrée', 'lay.roads.n': 'Géographie de référence, pas une sortie du modèle',
      'lay.tenure': 'Pourvoirie / tenure', 'lay.tenure.n': 'Pourvoiries, zecs, réserves — le hachuré rouge vous est FERMÉ et est exclu du classement',
      'lay.bounds': 'Limites et lieux', 'lay.bounds.n': 'Géographie de référence',
      'lay.water': 'Rivières et lacs', 'lay.water.n': 'Hydrographie cartographiée (OSM)',
      'lay.cross': 'Traverses de rivière', 'lay.cross.n': 'Rouge = embarcation requise · ambre = guéable',
      'lay.nodata': 'AUCUNE DONNÉE',

      'base.title': 'Fond de carte', 'base.opacity': 'Opacité', 'base.terrain': 'Relief',
      'base.3d': 'Relief 3D', 'base.exag': 'Exagération', 'base.more': 'Imagerie additionnelle',

      'ov.diy': 'CHASSE LIBRE POSSIBLE', 'ov.restricted': 'RESTREINT',
      'ov.confirm': 'élément à confirmer avant de partir', 'ov.confirms': 'éléments à confirmer avant de partir',
      'ov.looking': 'Ce que je recherche',
      'ov.why': 'Pourquoi ce score', 'ov.working': 'En votre faveur', 'ov.watch': 'Points de vigilance',
      'ov.allareas': '← tous les secteurs', 'ov.habitat': 'habitat', 'ov.packout': 'sortie de viande',
      'br.dates': 'Vos dates et le rut', 'br.how': 'Comment la chasser',
      'br.inout': 'Entrée et sortie', 'br.dayplan': 'Votre plan de journée', 'br.better': 'Comment faire mieux',
      'br.factors': 'Facteurs pondérés', 'br.sites': 'Sites',
      'br.valider': 'À valider sur le terrain.',
      'br.validerbody': 'Chaque marque ci-dessous est une hypothèse à valider à pied — le modèle lit l’habitat, pas les animaux.',

      'w.pickday': 'Choisissez une journée → les sites passent au vert quand le vent prévu convient à leur approche',
      'x.title': 'Exporter les points, trajets et secteurs de ce plan :',
      'x.gpx': 'GPX — OnX / Garmin', 'x.kml': 'KML — Google Earth', 'x.zones': 'inclure les zones du modèle',
      'lang.label': 'Langue'
    }
  };

  // Read everything off `global` rather than bare identifiers: in a browser they are
  // the same object, but bare `navigator`/`localStorage` silently resolve to the host's
  // own globals elsewhere (Node has both), which made this pick the wrong language.
  function detect() {
    try {
      const saved = global.localStorage && global.localStorage.getItem('transect_lang');
      if (saved && DICT[saved]) return saved;
    } catch (e) { /* private mode */ }
    const nav = global.navigator || {};
    const n = String(nav.language || nav.userLanguage || 'en').toLowerCase();
    return n.startsWith('fr') ? 'fr' : 'en';
  }

  let LANG = detect();

  const I18N = {
    get lang() { return LANG; },
    langs: ['en', 'fr'],
    /* Missing keys fall back to the supplied text, then to English, then to the key —
       so an untranslated string degrades to readable English, never to 'setup.s3'. */
    t(key, fallback) {
      const d = DICT[LANG] || DICT.en;
      if (d[key] != null) return d[key];
      if (fallback != null) return fallback;
      if (DICT.en[key] != null) return DICT.en[key];
      return key;
    },
    set(lang) {
      if (!DICT[lang]) return;
      LANG = lang;
      try { global.localStorage && global.localStorage.setItem('transect_lang', lang); } catch (e) { /* ignore */ }
      try { document.documentElement.setAttribute('lang', lang); } catch (e) { /* ignore */ }
      (I18N._on || []).forEach(fn => { try { fn(lang); } catch (e) { /* ignore */ } });
    },
    onChange(fn) { (I18N._on = I18N._on || []).push(fn); },
    /* Translate any element carrying data-i18n / data-i18n-ph (placeholder). */
    apply(root) {
      const r = root || document;
      r.querySelectorAll('[data-i18n]').forEach(el => {
        el.textContent = I18N.t(el.getAttribute('data-i18n'), el.textContent);
      });
      r.querySelectorAll('[data-i18n-ph]').forEach(el => {
        el.setAttribute('placeholder', I18N.t(el.getAttribute('data-i18n-ph'), el.getAttribute('placeholder')));
      });
    }
  };

  try { document.documentElement.setAttribute('lang', LANG); } catch (e) { /* ignore */ }
  global.I18N = I18N;
  global.t = I18N.t;
})(typeof window !== 'undefined' ? window : globalThis);
