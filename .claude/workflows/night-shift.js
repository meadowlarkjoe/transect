export const meta = {
  name: 'night-shift',
  description: 'Pick the top unblocked backlog ticket, implement it on a branch, adversarially review it, leave a proposal',
  whenToUse: 'Unattended progression on the Transect roadmap. Refuses to run until E0 (version control + tests) is closed.',
  phases: [
    { title: 'Gate',      detail: 'refuse to run if the repo is unsafe for unattended edits' },
    { title: 'Select',    detail: 'read BACKLOG.md, pick the top unblocked ticket' },
    { title: 'Implement', detail: 'one ticket, one branch, stop at ambiguity' },
    { title: 'Review',    detail: 'adversarial; defaults to reject' },
    { title: 'Report',    detail: 'write the proposal for morning review' },
  ],
}

/* The gate is the whole point of this workflow existing as a script rather than a
   prompt. An agent editing an unversioned 150 KB file with no test suite is not
   "autonomous progress", it is unrecoverable risk. So the first thing we do is try
   to prove the repo is safe, and stop if it isn't. */
phase('Gate')
const GATE_SCHEMA = {
  type: 'object',
  required: ['safe', 'reasons'],
  properties: {
    safe:    { type: 'boolean' },
    reasons: { type: 'array', items: { type: 'string' } },
  },
}
const gate = await agent(
  `Check whether this repo is safe for unattended edits. Report safe:false with reasons if ANY of:
   1. \`git status --porcelain\` in ~/moose-scout is non-empty (someone's work in progress).
   2. ~/transect-app is not a git repository (backlog ticket T0.1 — currently open).
   3. \`pytest\` cannot be run (backlog ticket T0.2 — currently open).
   Do not fix anything. Only report.`,
  { label: 'safety-gate', schema: GATE_SCHEMA, effort: 'low' })

if (!gate || !gate.safe) {
  log(`Gate closed — not running. ${(gate?.reasons || ['gate agent failed']).join(' | ')}`)
  return { ran: false, reasons: gate?.reasons || ['gate agent failed'] }
}

phase('Select')
const TICKET_SCHEMA = {
  type: 'object',
  required: ['id', 'title', 'epic', 'doneWhen', 'found'],
  properties: {
    id:       { type: 'string' },
    title:    { type: 'string' },
    epic:     { type: 'string' },
    doneWhen: { type: 'string' },
    found:    { type: 'boolean' },
  },
}
const ticket = await agent(
  `Read ~/moose-scout/docs/BACKLOG.md. Return the FIRST ticket that is status \`ready\`,
   is not marked \`human\`, and whose blockers are all \`done\`. Return found:false if
   there is no such ticket. Do not modify the file.`,
  { label: 'pick-ticket', schema: TICKET_SCHEMA, effort: 'low' })

if (!ticket || !ticket.found) {
  log('No unblocked ready ticket. Nothing to do.')
  return { ran: false, reasons: ['no unblocked ticket'] }
}
log(`Working ${ticket.id} — ${ticket.title}`)

phase('Implement')
const work = await agent(
  `Implement backlog ticket ${ticket.id} (${ticket.title}) from ~/moose-scout/docs/BACKLOG.md.
   Its exit criterion: ${ticket.doneWhen}
   It serves epic ${ticket.epic} — read ~/moose-scout/docs/roadmap.md for that epic's intent.
   Follow the transect-engineer rules exactly: one branch, one ticket, add a test, never
   change model weights or species/region configs, never deploy, and STOP and report
   rather than guessing if the ticket is ambiguous about anything a hunter would notice.
   Write your report to ~/moose-scout/docs/proposals/${ticket.id}.md`,
  { label: `impl:${ticket.id}`, agentType: 'transect-engineer' })

phase('Review')
/* Three independent reviewers rather than one, each told to refute. A single reviewer
   agreeing with a single implementer is two rolls of the same dice; the failure this
   guards against is a plausible-but-wrong change, which is exactly the kind a lone
   reviewer rationalises. Majority-reject kills it. */
const VERDICT_SCHEMA = {
  type: 'object',
  required: ['verdict', 'findings', 'couldNotVerify'],
  properties: {
    verdict:        { type: 'string', enum: ['REJECT', 'ACCEPT WITH CHANGES', 'ACCEPT'] },
    findings:       { type: 'array', items: { type: 'string' } },
    couldNotVerify: { type: 'array', items: { type: 'string' } },
  },
}
const LENSES = [
  'behaviour drift — does Fire Lake output change in any way the ticket did not sanction?',
  'test quality — does the test actually exercise the change, or does it pass vacuously?',
  'scope — did it touch model weights, species/region configs, deploy.sh, or the droplet?',
]
/* The reviewers check the CODE. None of them checks whether the resulting plan is one
   a hunter would actually walk — which is where every defect that reached Joe has
   lived. So a change that touches the engine gets read by someone playing the hunter. */
const reviews = (await parallel(LENSES.map(lens => () =>
  agent(`Adversarially review branch work for ticket ${ticket.id}.
         Report: ${work}
         Review through this lens specifically: ${lens}
         Try to REFUTE. Default to REJECT if you cannot verify the core claim.`,
        { label: `review:${lens.split(' ')[0]}`, agentType: 'transect-reviewer',
          schema: VERDICT_SCHEMA })
))).filter(Boolean)

let huntersRead = null
if (/synth|contract|access|habitat|terrain|behavior/i.test(String(work))) {
  huntersRead = await agent(
    `Pressure-test the plan this change produces. Run the pipeline on cached Fire Lake
     rasters if needed and read outputs/fire_lake/transect.json as a hunter would.
     Change under test: ${work}`,
    { label: 'hunter', agentType: 'transect-hunter', phase: 'Review' })
}

const rejects = reviews.filter(r => r.verdict === 'REJECT').length
const outcome = rejects >= 2 ? 'REJECTED' : rejects === 1 ? 'NEEDS ATTENTION' : 'READY FOR REVIEW'

phase('Report')
await agent(
  `Append a review summary to ~/moose-scout/docs/proposals/${ticket.id}.md.
   Outcome: ${outcome} (${rejects} of ${reviews.length} reviewers rejected).
   Reviews: ${JSON.stringify(reviews)}
   Hunter's read (null if the change did not touch the engine): ${JSON.stringify(huntersRead)}
   Write it for a human reading it in the morning: lead with the outcome and what needs
   their decision. Be plain about what was NOT verified — list every couldNotVerify item.
   Do not merge anything. Do not mark the backlog ticket done; only Joe does that.`,
  { label: 'report', effort: 'low' })

return { ran: true, ticket: ticket.id, outcome, rejects, reviewers: reviews.length,
         hunterRead: !!huntersRead }
