/**
 * Office State Manager.
 *
 * Bridges backend snapshot data and real-time WebSocket domain events
 * to visual canvas elements (agents, speech bubbles, project tokens).
 */

const STAGE_COORDINATES = {
  DISCOVERY: { x: 420, y: 140 },
  IDEA_SELECTION: { x: 420, y: 140 },
  RESEARCH: { x: 600, y: 140 },
  FACT_CHECK: { x: 600, y: 140 },
  SCRIPTING: { x: 130, y: 390 },
  HOOK_OPTIMIZATION: { x: 130, y: 390 },
  STORYBOARD: { x: 230, y: 390 },
  ASSET_GENERATION: { x: 680, y: 390 },
  VIDEO_GENERATION: { x: 730, y: 390 },
  VOICE_GENERATION: { x: 440, y: 390 },
  EDITING: { x: 780, y: 390 },
  QUALITY_CONTROL: { x: 780, y: 390 },
  READY_TO_PUBLISH: { x: 1010, y: 390 },
  PUBLISHING: { x: 1010, y: 390 },
  PUBLISHED: { x: 1060, y: 390 },
  ANALYTICS: { x: 130, y: 140 }, // Director Suite
  LEARNING: { x: 130, y: 140 },
};

export class OfficeState {
  constructor() {
    this.layout = null;
    this.agents = [];
    this.speechBubbles = [];
    this.projectTokens = [];
  }

  initFromLayout(layout) {
    this.layout = layout;
    this.agents = (layout.assignments || []).map(a => ({
      ...a,
      id: a.agent_id,
      runtime_state: a.runtime_state || 'IDLE',
      lifecycle: a.lifecycle || 'ACTIVE',
    }));
  }

  setAgents(agentsList) {
    const byId = new Map(this.agents.map(a => [a.id || a.agent_id, a]));
    for (const a of agentsList) {
      const id = a.id || a.agent_id;
      if (byId.has(id)) {
        Object.assign(byId.get(id), a);
      }
    }
  }

  addSpeechBubble(agentId, text, durationMs = 6000) {
    const agent = this.agents.find(a => (a.id || a.agent_id) === agentId);
    if (!agent) return;

    const bubble = {
      id: `${agentId}_${Date.now()}`,
      agentId,
      text,
      x: agent.x,
      y: agent.y,
      expiresAt: Date.now() + durationMs,
    };

    // Remove existing bubble for this agent
    this.speechBubbles = this.speechBubbles.filter(b => b.agentId !== agentId);
    this.speechBubbles.push(bubble);
  }

  updateProjectToken(workflowId, stage, title = 'Video Short') {
    const coords = STAGE_COORDINATES[stage] || { x: 600, y: 400 };
    const existing = this.projectTokens.find(t => t.id === workflowId);
    if (existing) {
      existing.stage = stage;
      existing.x = coords.x;
      existing.y = coords.y;
    } else {
      this.projectTokens.push({
        id: workflowId,
        title,
        stage,
        x: coords.x,
        y: coords.y,
      });
    }
  }

  cleanupExpiredBubbles() {
    const now = Date.now();
    this.speechBubbles = this.speechBubbles.filter(b => b.expiresAt > now);
  }

  handleDomainEvent(event) {
    const type = event.event_type;
    const payload = event.payload || {};

    if (type === 'agent.state_changed') {
      const agent = this.agents.find(a => (a.id || a.agent_id) === event.aggregate_id);
      if (agent) {
        agent.runtime_state = payload.runtime_state || agent.runtime_state;
      }
    } else if (type === 'agent.message_sent') {
      this.addSpeechBubble(event.aggregate_id, payload.text || payload.content || 'Working on task...');
    } else if (type === 'agent.paused') {
      const agent = this.agents.find(a => (a.id || a.agent_id) === event.aggregate_id);
      if (agent) {
        agent.lifecycle = 'PAUSED';
      }
    } else if (type === 'agent.resumed') {
      const agent = this.agents.find(a => (a.id || a.agent_id) === event.aggregate_id);
      if (agent) {
        agent.lifecycle = 'ACTIVE';
      }
    } else if (type === 'agent.run_completed') {
      const agent = this.agents.find(a => (a.id || a.agent_id) === payload.agent_id);
      if (agent) {
        agent.runtime_state = 'IDLE';
        if (payload.status === 'SUCCEEDED') {
          this.addSpeechBubble(agent.id, `Completed: ${payload.task_type || 'task'} ✓`, 4000);
        }
      }
    } else if (type.startsWith('workflow.')) {
      if (payload.current_stage) {
        this.updateProjectToken(event.aggregate_id, payload.current_stage);
      }
    }
  }
}
