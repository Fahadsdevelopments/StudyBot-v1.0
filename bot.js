const { Client, Intents } = require('discord.js');
const axios = require('axios');
const FormData = require('form-data');
require('dotenv').config({ path: '.env' });

const API = 'https://your-railway-url.up.railway.app';

const client = new Client({
  intents: [
    Intents.FLAGS.GUILDS,
    Intents.FLAGS.GUILD_MESSAGES,
    Intents.FLAGS.MESSAGE_CONTENT,
  ]
});

const pendingUploads = new Map();
const pendingSubject = new Map();
const pendingFamiliarity = new Map();

client.once('ready', (c) => {
  console.log(`✅ StudyBot online as ${c.user.tag}`);
});

client.on('messageCreate', async (message) => {
  if (message.author.bot) return;
  const content = message.content.trim();
  const userId = message.author.id;

  // ── STEP 1: Doc type (1-4) ─────────────────────────────────
  if (['1', '2', '3', '4'].includes(content) && pendingUploads.has(userId)) {
    const pending = pendingUploads.get(userId);
    pendingUploads.delete(userId);
    const docTypes = { '1': 'assignment', '2': 'lecture_slides', '3': 'past_paper', '4': 'other' };
    const docTypeLabels = { '1': 'Assignment', '2': 'Lecture Slides', '3': 'Past Exam Paper', '4': 'Other' };
    const docType = docTypes[content];
    pendingSubject.set(userId, { ...pending, docType });

    try {
      const subjectsRes = await axios.get(`${API}/subjects`);
      const subjects = subjectsRes.data.subjects;
      if (!subjects.length) {
        return message.reply(
          `📄 Got it — **${docTypeLabels[content]}**\n\n` +
          `No subjects added yet. Type **NONE** to skip, or add with:\n` +
          `\`!add_subject CODE Full Subject Name\``
        );
      }
      const subjectList = subjects.map(s => `**${s.code}**`).join(' · ');
      return message.reply(
        `📄 Got it — **${docTypeLabels[content]}**\n\n` +
        `Which subject?\n\n${subjectList}\n\n` +
        `_(or type **NONE** to skip)_`
      );
    } catch (e) {
      return message.reply(`❌ Could not fetch subjects: ${e.message}`);
    }
  }

  // ── STEP 2: Subject code ───────────────────────────────────
  if (pendingSubject.has(userId)) {
    const pending = pendingSubject.get(userId);
    try {
      const subjectsRes = await axios.get(`${API}/subjects`);
      const validCodes = [...subjectsRes.data.subjects.map(s => s.code), 'NONE'];
      if (validCodes.includes(content.toUpperCase())) {
        pendingSubject.delete(userId);
        const courseCode = content.toUpperCase() === 'NONE' ? null : content.toUpperCase();
        const subjectLabel = courseCode || 'No subject';
        const thinking = await message.reply(
          `📄 Processing for **${subjectLabel}**...\n_(This may take 20-30 seconds)_`
        );
        try {
          const form = new FormData();
          form.append('file', pending.buffer, { filename: pending.filename, contentType: 'application/pdf' });
          const url = courseCode
            ? `${API}/upload?doc_type=${pending.docType}&course_code=${courseCode}`
            : `${API}/upload?doc_type=${pending.docType}`;
          const uploadRes = await axios.post(url, form, { headers: form.getHeaders(), timeout: 120000 });
          const data = uploadRes.data;
          if (!data.success) return thinking.edit('❌ Failed to process PDF.');

          if (pending.docType === 'lecture_slides') {
            return thinking.edit(
              `📚 **Lecture slides saved!** ${courseCode ? `[${courseCode}]` : ''}\n\n` +
              `📝 **Summary:** ${data.summary}\n🏷️ **Topics:** ${data.topics.join(', ')}\n\n` +
              `These topics will improve assignment analysis for ${courseCode || 'this course'}.`
            );
          }
          if (pending.docType === 'past_paper') {
            return thinking.edit(
              `📋 **Past exam paper saved!** ${courseCode ? `[${courseCode}]` : ''}\n\n` +
              `📝 **Summary:** ${data.summary}\n🏷️ **Topics:** ${data.topics.join(', ')}\n\n` +
              `Exam patterns will influence priority scores for ${courseCode || 'this course'}.`
            );
          }
          const taskLines = data.tasks.length > 0
            ? data.tasks.map((t, i) => `${i + 1}. **${t.title}** — ${t.complexity} — Est: ${t.estimated_hours}h`).join('\n')
            : 'No specific tasks found.';
          pendingFamiliarity.set(userId, { docId: data.doc_id });
          return thinking.edit(
            `📄 **${data.filename}** ${courseCode ? `[${courseCode}]` : ''}\n\n` +
            `📝 **Summary:** ${data.summary}\n🏷️ **Topics:** ${data.topics.join(', ')}\n\n` +
            `✅ **${data.tasks_found} tasks extracted:**\n${taskLines}\n\n` +
            `📊 **How familiar are you with these topics?**\n` +
            `**1** — Never seen this  **2** — Shaky  **3** — Know basics\n` +
            `**4** — Comfortable  **5** — Very confident`
          );
        } catch (e) {
          return thinking.edit(`❌ Failed to process PDF: ${e.message}`);
        }
      }
    } catch (e) { console.error('Subject fetch error:', e.message); }
  }

  // ── STEP 3: Familiarity (1-5) ──────────────────────────────
  if (['1', '2', '3', '4', '5'].includes(content) && pendingFamiliarity.has(userId)) {
    const pending = pendingFamiliarity.get(userId);
    pendingFamiliarity.delete(userId);
    const multipliers = { 1: 2.0, 2: 1.5, 3: 1.0, 4: 0.7, 5: 0.5 };
    const labels = {
      1: "Added extra time — new material 📚", 2: "Added buffer time 🔍",
      3: "Standard estimate ✅", 4: "Reduced time — you know this 👍", 5: "Minimal time — you've got this! ⚡"
    };
    try {
      await axios.post(`${API}/tasks/adjust-time`, { multiplier: multipliers[parseInt(content)], doc_id: pending.docId });
      return message.reply(
        `⏱️ **Time estimates adjusted!**\n${labels[parseInt(content)]}\n\n` +
        `Type **!tasks** to see your list or **!schedule** to plan your day.`
      );
    } catch (e) { return message.reply('❌ Could not adjust estimates.'); }
  }

  // ── PDF Upload ─────────────────────────────────────────────
  if (message.attachments.size > 0) {
    const attachment = message.attachments.first();
    if (attachment.name.toLowerCase().endsWith('.pdf')) {
      try {
        const response = await axios.get(attachment.url, { responseType: 'arraybuffer' });
        pendingUploads.set(userId, { buffer: Buffer.from(response.data), filename: attachment.name });
        return message.reply(
          `📎 **${attachment.name}** received!\n\n` +
          `What type?\n**1️⃣** Assignment  **2️⃣** Lecture slides  **3️⃣** Past exam paper  **4️⃣** Other\n\n_(Reply with just the number)_`
        );
      } catch (e) { return message.reply(`❌ Could not download PDF: ${e.message}`); }
    }
  }

  // ── !tasks [code] ──────────────────────────────────────────
  if (content === '!tasks' || content.startsWith('!tasks ')) {
    const code = content.split(' ')[1]?.toUpperCase() || null;
    try {
      if (code) {
        const res = await axios.get(`${API}/subjects/${code}/tasks`);
        const tasks = res.data.tasks;
        if (!tasks.length) return message.reply(`📋 No pending tasks for **${res.data.subject}**.`);
        const lines = tasks.map((t, i) => `${i + 1}. **${t.title}** — ${t.complexity} — Est: ${t.estimated_hours}h`);
        return message.reply(`📋 **${res.data.subject}**\n\n${lines.join('\n')}`);
      } else {
        const res = await axios.get(`${API}/tasks/pending`);
        const tasks = res.data.tasks;
        if (!tasks.length) return message.reply('📋 No pending tasks! Upload a PDF to get started.');
        const lines = tasks.map((t, i) =>
          `${i + 1}. **${t.title}** [${t.course_code || '—'}] — ${t.complexity} — Est: ${t.estimated_hours}h`
        );
        return message.reply(`📋 **Your Pending Tasks**\n\n${lines.join('\n')}`);
      }
    } catch (e) { return message.reply('❌ Could not fetch tasks.'); }
  }

  // ── !schedule ──────────────────────────────────────────────
  if (content.startsWith('!schedule')) {
    try {
      const hours = parseInt(content.split(' ')[1]) || 6;
      const res = await axios.get(`${API}/schedule?hours_available=${hours}`);
      if (!res.data.schedule.length) return message.reply('📅 No tasks to schedule!');
      const emojis = { '09': '🕘', '10': '🕙', '11': '🕚', '12': '🕛', '13': '🕐', '14': '🕑', '15': '🕒', '16': '🕓', '17': '🕔', '18': '🕕' };
      const lines = res.data.schedule.map(b => {
        const e = emojis[b.start_time.split(':')[0]] || '🕐';
        return `${e} ${b.start_time}–${b.end_time} | **${b.title}** [${b.course_code || '—'}] (${b.complexity})`;
      });
      const protectedNote = res.data.protected_blocks > 0 ? `\n🔒 ${res.data.protected_blocks} protected block(s) skipped` : '';
      return message.reply(
        `📅 **Today's Study Schedule**\n\n${lines.join('\n')}\n\n` +
        `⏱️ Total: **${res.data.hours_scheduled}h**${protectedNote}\n` +
        `Type **!sync** to push to Google Calendar.`
      );
    } catch (e) { return message.reply('❌ Could not generate schedule.'); }
  }

  // ── !sync ──────────────────────────────────────────────────
  if (content.startsWith('!sync')) {
    try {
      const hours = parseInt(content.split(' ')[1]) || 6;
      const thinking = await message.reply('📅 Syncing to Google Calendar...');
      const res = await axios.post(`${API}/schedule/sync-calendar?hours_available=${hours}`);
      if (!res.data.success) return thinking.edit(`❌ ${res.data.message || res.data.error}`);
      const events = res.data.events || [];
      if (!events.length) return thinking.edit('❌ No tasks to sync.');
      return thinking.edit(
        `✅ **Synced ${events.length} blocks to Google Calendar!**\n\n` +
        events.map((e, i) => `${i + 1}. **${e.title}**`).join('\n')
      );
    } catch (e) { return message.reply(`❌ Could not sync: ${e.message}`); }
  }

  // ── !done ──────────────────────────────────────────────────
  if (content.startsWith('!done ')) {
    const taskName = content.slice(6).trim().toLowerCase();
    try {
      const res = await axios.get(`${API}/tasks/pending`);
      const match = res.data.tasks.find(t => t.title.toLowerCase().includes(taskName));
      if (!match) return message.reply(`❌ No pending task matching "${taskName}".`);
      await axios.post(`${API}/tasks/${match.doc_id}/complete`);
      return message.reply(`✅ Marked **${match.title}** as complete!`);
    } catch (e) { return message.reply('❌ Could not complete task.'); }
  }

  // ── !start ─────────────────────────────────────────────────
  if (content.startsWith('!start ')) {
    const taskName = content.slice(7).trim();
    try {
      const res = await axios.post(`${API}/sessions/start`, { user_id: userId, task_title: taskName });
      if (!res.data.success) return message.reply(`❌ ${res.data.message}`);
      return message.reply(
        `⏱️ **Started: ${res.data.task_title}**\n` +
        `Estimated: **${res.data.estimated_hours}h** | Type **!stop** when done.`
      );
    } catch (e) { return message.reply(`❌ Could not start session: ${e.message}`); }
  }

  // ── !stop ──────────────────────────────────────────────────
  if (content === '!stop') {
    try {
      const res = await axios.post(`${API}/sessions/stop`, { user_id: userId });
      if (!res.data.success) return message.reply(`❌ ${res.data.message}`);
      const actualMins = Math.round(res.data.actual_hours * 60);
      const estimatedMins = Math.round(res.data.estimated_hours * 60);
      const levelUpMsg = res.data.leveled_up
        ? `\n\n🎉 **LEVEL UP!** You reached **Level ${res.data.level} — ${res.data.level_name}** in ${res.data.task_title.split(' ')[0]}!`
        : '';
      return message.reply(
        `⏹️ **Done: ${res.data.task_title}**\n\n` +
        `⏱️ Est: **${estimatedMins}min** | Actual: **${actualMins}min**\n\n` +
        `${res.data.feedback}\n${res.data.skill_change}\n\n` +
        `✨ **+${res.data.xp_earned} XP** | Total: ${res.data.total_xp} XP | ` +
        `Level ${res.data.level} ${res.data.level_name} | Next level in ${res.data.xp_to_next} XP` +
        `${levelUpMsg}`
      );
    } catch (e) { return message.reply(`❌ Could not stop session: ${e.message}`); }
  }

  // ── !level ─────────────────────────────────────────────────
  if (content === '!level') {
    try {
      const res = await axios.get(`${API}/xp?user_id=${userId}`);
      const profiles = res.data.profiles;
      if (!profiles.length) {
        return message.reply('🎮 No XP yet! Complete tasks with !start and !stop to earn XP.');
      }
      const lines = profiles.map(p =>
        `**${p.course_code}** — Level ${p.level} ${p.level_name} — ${p.xp} XP (${p.xp_to_next} to next)`
      );
      return message.reply(`🎮 **Your Level Progress**\n\n${lines.join('\n')}`);
    } catch (e) { return message.reply('❌ Could not fetch XP profile.'); }
  }

  // ── !skills ────────────────────────────────────────────────
  if (content === '!skills') {
    try {
      const res = await axios.get(`${API}/skills?user_id=${userId}`);
      const skills = res.data.skills;
      if (!skills.length) return message.reply('📊 No skill data yet! Use !start and !stop.');
      const lines = skills.map(s => `**${s.topic}** — ${s.level} — ${s.sessions_count} session(s)`);
      return message.reply(`📊 **Your Skill Profile**\n\n${lines.join('\n')}`);
    } catch (e) { return message.reply('❌ Could not fetch skills.'); }
  }

  // ── !exam add [code] [date] [time] [location] ──────────────
  if (content.startsWith('!exam add ')) {
    const parts = content.slice(10).trim().split(' ');
    const code = parts[0]?.toUpperCase();
    const date = parts[1]; // YYYY-MM-DD
    const time = parts[2] || '';
    const location = parts.slice(3).join(' ') || '';

    if (!code || !date) {
      return message.reply(
        '❌ Usage: `!exam add CODE YYYY-MM-DD HH:MM Location`\n' +
        'Example: `!exam add GTI2 2026-05-15 10:00 Room A1.04`'
      );
    }
    try {
      const res = await axios.post(`${API}/exams`, {
        course_code: code, exam_date: date, exam_time: time, location
      });
      return message.reply(
        `📝 **Exam saved!**\n\n` +
        `📚 **${res.data.subject_name}** [${code}]\n` +
        `📅 Date: **${date}** ${time ? `at **${time}**` : ''}\n` +
        `📍 Location: **${location || 'TBD'}**\n` +
        `⏳ **${res.data.days_until} days** until exam`
      );
    } catch (e) {
      const msg = e.response?.data?.detail || e.message;
      return message.reply(`❌ ${msg}`);
    }
  }

  // ── !exams ─────────────────────────────────────────────────
  if (content === '!exams') {
    try {
      const res = await axios.get(`${API}/exams`);
      const exams = res.data.exams;
      if (!exams.length) {
        return message.reply('📝 No exams scheduled. Use `!exam add CODE YYYY-MM-DD HH:MM Location`');
      }
      const lines = exams.map(e =>
        `${e.urgency} **${e.subject_name}** [${e.course_code}]\n` +
        `   📅 ${e.exam_date}${e.exam_time ? ` at ${e.exam_time}` : ''} | ` +
        `📍 ${e.location || 'TBD'} | ⏳ **${e.days_until} days**`
      );
      return message.reply(`📝 **Upcoming Exams**\n\n${lines.join('\n\n')}`);
    } catch (e) { return message.reply('❌ Could not fetch exams.'); }
  }

  // ── !exam remove [code] ────────────────────────────────────
  if (content.startsWith('!exam remove ')) {
    const code = content.slice(13).trim().toUpperCase();
    try {
      await axios.delete(`${API}/exams/${code}`);
      return message.reply(`🗑️ Removed exam for **${code}**`);
    } catch (e) { return message.reply(`❌ Exam for ${code} not found.`); }
  }

  // ── !grade [code] [grade] [assessment] ────────────────────
  if (content.startsWith('!grade ')) {
    const parts = content.slice(7).trim().split(' ');
    const code = parts[0]?.toUpperCase();
    const grade = parts[1];
    const assessment = parts[2] || 'final';

    if (!code || !grade) {
      return message.reply(
        '❌ Usage: `!grade CODE GRADE [assessment]`\n' +
        'Example: `!grade GTI1 2.3` or `!grade SE 1.7 midterm`\n' +
        'Grade scale: 1.0 (best) to 5.0 (fail)'
      );
    }
    try {
      const res = await axios.post(`${API}/grades`, { course_code: code, grade: parseFloat(grade), assessment });
      const passedEmoji = res.data.passed ? '✅' : '❌';
      return message.reply(
        `${passedEmoji} **Grade logged!**\n\n` +
        `📚 **${res.data.subject_name}** [${code}]\n` +
        `📊 Grade: **${grade}** — ${res.data.grade_label}\n` +
        `🎓 ECTS: **${res.data.ects}** | ${res.data.passed ? 'Passed ✅' : 'Failed ❌'}`
      );
    } catch (e) {
      const msg = e.response?.data?.detail || e.message;
      return message.reply(`❌ ${msg}`);
    }
  }

  // ── !grades ────────────────────────────────────────────────
  if (content === '!grades') {
    try {
      const res = await axios.get(`${API}/grades`);
      const { grades, gpa, ects_earned, ects_total } = res.data;
      if (!grades.length) {
        return message.reply('📊 No grades logged yet. Use `!grade CODE GRADE`');
      }
      const lines = grades.map(g =>
        `**${g.course_code}** — ${g.grade} (${g.assessment}) ${g.passed ? '✅' : '❌'} — ${g.ects} ECTS`
      );
      const gpaLine = gpa ? `\n\n📈 **GPA: ${gpa}** (weighted by ECTS)` : '';
      const ectsLine = `\n🎓 **ECTS: ${ects_earned}/${ects_total}**`;
      return message.reply(`📊 **Your Grades**\n\n${lines.join('\n')}${gpaLine}${ectsLine}`);
    } catch (e) { return message.reply('❌ Could not fetch grades.'); }
  }

  // ── !protect [day/daily] [start] [end] [label] ────────────
  if (content.startsWith('!protect ')) {
    const parts = content.slice(9).trim().split(' ');
    const day = parts[0];
    const start_time = parts[1];
    const end_time = parts[2];
    const label = parts.slice(3).join(' ') || 'Personal time';

    if (!day || !start_time || !end_time) {
      return message.reply(
        '❌ Usage: `!protect DAY HH:MM HH:MM Label`\n' +
        'Examples:\n' +
        '`!protect Monday 18:00 22:00 Girlfriend time`\n' +
        '`!protect daily 22:00 23:59 Evening wind-down`\n' +
        '`!protect Saturday 00:00 23:59 Weekend free`\n\n' +
        'Valid days: Monday Tuesday Wednesday Thursday Friday Saturday Sunday daily'
      );
    }
    try {
      await axios.post(`${API}/protected`, { day, start_time, end_time, label });
      return message.reply(
        `🔒 **Protected time added!**\n\n` +
        `📅 **${day}** from **${start_time}** to **${end_time}**\n` +
        `🏷️ Label: **${label}**\n\n` +
        `The schedule will never fill this window with study tasks.`
      );
    } catch (e) {
      const msg = e.response?.data?.detail || e.message;
      return message.reply(`❌ ${msg}`);
    }
  }

  // ── !protected ─────────────────────────────────────────────
  if (content === '!protected') {
    try {
      const res = await axios.get(`${API}/protected`);
      const blocks = res.data.blocks;
      if (!blocks.length) {
        return message.reply(
          '🔓 No protected time blocks.\n' +
          'Use `!protect DAY HH:MM HH:MM Label` to add one.'
        );
      }
      const lines = blocks.map(b =>
        `🔒 **${b.day}** ${b.start_time}–${b.end_time} — ${b.label}`
      );
      return message.reply(`🔒 **Protected Time Blocks**\n\n${lines.join('\n')}`);
    } catch (e) { return message.reply('❌ Could not fetch protected blocks.'); }
  }

  // ── !unprotect [day] [start] ───────────────────────────────
  if (content.startsWith('!unprotect ')) {
    const parts = content.slice(11).trim().split(' ');
    const day = parts[0];
    const start_time = parts[1];
    if (!day || !start_time) {
      return message.reply('❌ Usage: `!unprotect DAY HH:MM`\nExample: `!unprotect Monday 18:00`');
    }
    try {
      await axios.delete(`${API}/protected`, { data: { day, start_time } });
      return message.reply(`🔓 Removed protected block: **${day}** at **${start_time}**`);
    } catch (e) { return message.reply('❌ Block not found.'); }
  }

  // ── !analytics ─────────────────────────────────────────────
  if (content.startsWith('!analytics')) {
    const days = parseInt(content.split(' ')[1]) || 30;
    try {
      const res = await axios.get(`${API}/analytics?user_id=${userId}&days=${days}`);
      const a = res.data;

      if (a.tasks_completed === 0) {
        return message.reply(
          `📊 No study sessions in the last ${days} days.\nUse **!start** and **!stop** to track your study time.`
        );
      }

      // Subject breakdown
      const subjectLines = Object.entries(a.subject_breakdown)
        .sort((x, y) => y[1] - x[1])
        .map(([code, hours]) => `**${code}**: ${hours.toFixed(1)}h`)
        .join(' · ');

      // Top mastery topics
      const masteryLines = Object.entries(a.mastery_curves)
        .sort((x, y) => x[1].avg_ratio - y[1].avg_ratio)
        .slice(0, 5)
        .map(([topic, m]) => `**${topic}** — ${m.level} (${m.sessions} sessions, ${m.trend})`)
        .join('\n');

      // Best study days
      const bestDays = a.best_study_days.slice(0, 3)
        .map(([day, hours]) => `${day}: ${hours.toFixed(1)}h`)
        .join(', ');

      return message.reply(
        `📊 **Analytics — Last ${days} days**\n\n` +
        `⏱️ **Total study time:** ${a.total_hours}h\n` +
        `✅ **Tasks completed:** ${a.tasks_completed}\n\n` +
        `📚 **By subject:**\n${subjectLines || 'No data'}\n\n` +
        `🧠 **Topic mastery:**\n${masteryLines || 'No topic data yet'}\n\n` +
        `📅 **Best study days:** ${bestDays || 'No data'}\n\n` +
        `_Tip: Use \`!analytics 7\` for last 7 days_`
      );
    } catch (e) { return message.reply('❌ Could not fetch analytics.'); }
  }

  // ── !subjects ──────────────────────────────────────────────
  if (content === '!subjects') {
    try {
      const res = await axios.get(`${API}/subjects`);
      const subjects = res.data.subjects;
      if (!subjects.length) return message.reply('📚 No subjects. Use `!add_subject CODE Name`');
      const lines = subjects.map(s => `**${s.code}** — ${s.name}${s.ects ? ` (${s.ects} ECTS)` : ''}`);
      return message.reply(`📚 **Your Subjects**\n\n${lines.join('\n')}`);
    } catch (e) { return message.reply('❌ Could not fetch subjects.'); }
  }

  // ── !add_subject [code] [name] ─────────────────────────────
  if (content.startsWith('!add_subject ')) {
    const parts = content.slice(13).trim().split(' ');
    const code = parts[0].toUpperCase();
    const name = parts.slice(1).join(' ');
    if (!code || !name) {
      return message.reply('❌ Usage: `!add_subject CODE Full Name`');
    }
    try {
      await axios.post(`${API}/subjects`, { code, name });
      return message.reply(`✅ Added **${code}** — ${name}`);
    } catch (e) {
      return message.reply(`❌ ${e.response?.data?.detail || e.message}`);
    }
  }

  // ── !remove_subject ────────────────────────────────────────
  if (content.startsWith('!remove_subject ')) {
    const code = content.slice(16).trim().toUpperCase();
    try {
      await axios.delete(`${API}/subjects/${code}`);
      return message.reply(`🗑️ Removed **${code}**`);
    } catch (e) { return message.reply(`❌ Subject ${code} not found.`); }
  }

  // ── !docs [code] ───────────────────────────────────────────
  if (content === '!docs' || content.startsWith('!docs ')) {
    const code = content.split(' ')[1]?.toUpperCase() || null;
    try {
      if (code) {
        const res = await axios.get(`${API}/subjects/${code}/docs`);
        if (!res.data.documents.length) return message.reply(`📁 No documents for **${res.data.subject}**.`);
        const lines = res.data.documents.map((d, i) => `${i + 1}. **${d.filename}** [${d.doc_type}] — ${d.summary}`);
        return message.reply(`📁 **${res.data.subject}**\n\n${lines.join('\n')}`);
      } else {
        const res = await axios.get(`${API}/documents`);
        if (!res.data.documents.length) return message.reply('📁 No documents uploaded yet.');
        const lines = res.data.documents.map((d, i) =>
          `${i + 1}. **${d.filename}** [${d.doc_type || 'unknown'}${d.course_code ? ' · ' + d.course_code : ''}]`
        );
        return message.reply(`📁 **All Documents**\n\n${lines.join('\n')}`);
      }
    } catch (e) { return message.reply('❌ Could not fetch documents.'); }
  }

  // ── !clear ─────────────────────────────────────────────────
  if (content === '!clear') {
    try {
      const res = await axios.delete(`${API}/tasks/clear-all`);
      return message.reply(`🗑️ Cleared **${res.data.deleted}** tasks.`);
    } catch (e) { return message.reply('❌ Could not clear tasks.'); }
  }

  // ── !health ────────────────────────────────────────────────
  if (content === '!health') {
    try {
      const res = await axios.get(`${API}/health`);
      return message.reply(`✅ API online | DB: ${res.data.db} | v${res.data.version}`);
    } catch (e) { return message.reply('❌ API is offline.'); }
  }

  // ── !help ──────────────────────────────────────────────────
  if (content === '!help') {
    return message.reply(
      `📚 **StudyBot Commands**\n\n` +
      `**📄 Documents**\n` +
      `Attach PDF → type → subject → familiarity\n\n` +
      `**📋 Tasks**\n` +
      `\`!tasks\` · \`!tasks GTI1\` · \`!done [name]\` · \`!clear\`\n\n` +
      `**📅 Schedule & Calendar**\n` +
      `\`!schedule\` · \`!schedule 4\` · \`!sync\`\n\n` +
      `**⏱️ Timer & Skills**\n` +
      `\`!start [task]\` · \`!stop\` · \`!skills\`\n\n` +
      `**🎮 Gamification**\n` +
      `\`!level\` — XP and level per subject\n\n` +
      `**📝 Exams**\n` +
      `\`!exams\` · \`!exam add CODE DATE TIME LOCATION\` · \`!exam remove CODE\`\n\n` +
      `**📊 Grades & ECTS**\n` +
      `\`!grades\` · \`!grade CODE GRADE [assessment]\`\n\n` +
      `**🔒 Protected Time**\n` +
      `\`!protected\` · \`!protect DAY HH:MM HH:MM Label\` · \`!unprotect DAY HH:MM\`\n\n` +
      `**📈 Analytics**\n` +
      `\`!analytics\` · \`!analytics 7\` (last 7 days)\n\n` +
      `**📚 Subjects**\n` +
      `\`!subjects\` · \`!add_subject CODE Name\` · \`!remove_subject CODE\`\n\n` +
      `**!health** — API status`
    );
  }

});

client.login(process.env.DISCORD_TOKEN);
