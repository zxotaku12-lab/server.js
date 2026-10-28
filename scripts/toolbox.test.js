const assert = require('assert');
const { getCommands } = require('../commands');
const commands = require('../commands/toolbox');
const { HttpInteraction } = require('../lib/http-interaction');
(async () => {
  const registry = getCommands();
  const actions = registry.json.reduce((n, c) => n + (c.options?.some(o => o.type === 1) ? c.options.filter(o => o.type === 1).length : 1), 0);
  assert.strictEqual(actions, 153); assert(registry.json.length <= 100);
  for (const command of commands) {
    const json = command.data.toJSON(); assert(json.options.length <= 25);
    for (const sub of json.options) {
      let result;
      const i = { options: { getSubcommand: () => sub.name, getString: () => 'hello world', getNumber: () => 2 }, reply: async x => { result = x; } };
      await command.execute(i); assert(result && result.content && result.content.length <= 2000, `${json.name} ${sub.name}`);
      assert.deepStrictEqual(result.allowedMentions, { parse: [] });
    }
  }
  let result;
  const math = commands.find(c => c.data.name === 'math-tools');
  await math.execute({ options: { getSubcommand: () => 'sqrt', getNumber: () => -1 }, reply: async x => { result = x; } }); assert.match(result.content, /Invalid/);
  const convert = commands.find(c => c.data.name === 'convert');
  await convert.execute({ options: { getSubcommand: () => 'celsius-fahrenheit', getNumber: () => 0 }, reply: async x => { result = x; } }); assert.equal(result.content, '32');
  const payload = { type: 2, data: { name: 'calculate', options: [{ type: 1, name: 'add', options: [{ name: 'first', type: 10, value: 2 }, { name: 'second', type: 10, value: 3 }] }] }, user: { id: '1', username: 'test' } };
  const http = new HttpInteraction(payload); assert.equal(http.options.getSubcommand(), 'add'); assert.equal(http.options.getNumber('first'), 2);
  await commands.find(c => c.data.name === 'calculate').execute(http); assert.equal(http.response.data.content, '5');
  console.log('153 command actions and toolbox tests passed');
})().catch(e => { console.error(e); process.exitCode = 1; });
