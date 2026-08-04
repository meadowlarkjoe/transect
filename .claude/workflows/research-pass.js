export const meta = {
  name: 'research-pass',
  description: 'Deep research pass for a species × region cell: biology profile + verified data sources, both adversarially reviewed, landed as proposals',
  whenToUse: 'Opening a new region or species on the roadmap. Pass {species, region} as args.',
  phases: [
    { title: 'Research', detail: 'biology profile and data-source sweep, in parallel' },
    { title: 'Verify',   detail: 'refute the citations and re-run the fetches' },
    { title: 'Draft',    detail: 'assemble reviewed config proposals' },
  ],
}

/* args: {species, region} — e.g. {species:'moose', region:'ontario'} */
const species = (args && args.species) || 'moose'
const region  = (args && args.region)  || 'quebec_boreal'
log(`Research pass: ${species} × ${region}`)

const PROFILE_SCHEMA = {
  type: 'object',
  required: ['confidence', 'yaml', 'citations', 'carriedAssumptions', 'gaps'],
  properties: {
    confidence:         { type: 'string', enum: ['high', 'moderate', 'low'] },
    yaml:               { type: 'string' },
    citations:          { type: 'array', items: { type: 'string' } },
    carriedAssumptions: { type: 'array', items: { type: 'string' } },
    gaps:               { type: 'array', items: { type: 'string' } },
  },
}
const SOURCES_SCHEMA = {
  type: 'object',
  required: ['verified', 'fallback', 'absent'],
  properties: {
    verified: { type: 'array', items: {
      type: 'object',
      required: ['layer', 'source', 'testResult'],
      properties: {
        layer:      { type: 'string' },
        source:     { type: 'string' },
        endpoint:   { type: 'string' },
        testResult: { type: 'string' },
        crs:        { type: 'string' },
        licence:    { type: 'string' },
      },
    }},
    fallback: { type: 'array', items: { type: 'string' } },
    absent:   { type: 'array', items: { type: 'string' } },
  },
}

/* Biology and data availability are independent questions, so they run concurrently —
   but each is verified before either is trusted, because a beautiful profile for a
   region whose data does not exist is worth nothing. */
phase('Research')
const [profile, sources] = await parallel([
  () => agent(
    `Research ${species} habitat selection and behaviour for region: ${region}.
     Produce a structured, cited profile in the shape of config/species/moose.yaml.
     Follow the transect-researcher rules: primary sources only, latitude and
     subspecies matter, seek the disconfirming study, and never invent a number to
     fill a slot. The "gaps" list must be honest — an empty one reads as insufficient
     looking, not completeness.`,
    { label: `bio:${species}`, agentType: 'transect-researcher', schema: PROFILE_SCHEMA }),

  () => agent(
    `Find and VERIFY open geodata for region: ${region}, for the layers the Transect
     engine consumes (DEM, landcover, hydro, roads, fire history, tenure, harvest stats).
     Follow the transect-datasource rules: prove every source with a real fetch against
     a real bbox inside the region and record status, feature count, response time, CRS
     and licence. Documentation alone is not verification.`,
    { label: `data:${region}`, agentType: 'transect-datasource', schema: SOURCES_SCHEMA }),
])

phase('Verify')
/* Both artefacts get attacked before anything is drafted. The researcher and the
   data scout are each optimistic about their own output; neither reviews itself. */
const checks = (await parallel([
  () => agent(
    `Adversarially review this ${species} × ${region} biology profile. Open the three
     highest-leverage citations and confirm they say what is claimed — a real citation
     attached to a number it does not support is the failure mode here. Flag any value
     carried from another region or subspecies without argument.
     Profile: ${JSON.stringify(profile)}`,
    { label: 'verify:bio', agentType: 'transect-reviewer' }),

  () => agent(
    `Adversarially review this data-source sweep for ${region}. Re-run at least one
     verification fetch yourself. Judge whether the test bbox was representative or
     chosen where data happens to exist — Québec's écoforestière stops at the 52nd
     parallel, which a centrally-chosen bbox would hide.
     Sources: ${JSON.stringify(sources)}`,
    { label: 'verify:data', agentType: 'transect-reviewer' }),
])).filter(Boolean)

phase('Draft')
await agent(
  `Write ~/moose-scout/docs/proposals/${species}-${region}.md containing:
   1. The proposed config/species and config/regions YAML, clearly marked PROPOSAL — NOT MERGED.
   2. Citations, carried assumptions, and gaps, verbatim from the research.
   3. The two adversarial reviews and what they found.
   4. A "decisions for Joe" section listing every judgement call, especially any
      parameter with weak support and any layer marked absent.
   Profile: ${JSON.stringify(profile)}
   Sources: ${JSON.stringify(sources)}
   Reviews: ${JSON.stringify(checks)}
   Do NOT write to config/. This is a proposal for human review.`,
  { label: 'draft', effort: 'low' })

return {
  species, region,
  confidence: profile?.confidence,
  verifiedLayers: sources?.verified?.length ?? 0,
  absentLayers: sources?.absent ?? [],
  gaps: profile?.gaps ?? [],
  proposal: `docs/proposals/${species}-${region}.md`,
}
