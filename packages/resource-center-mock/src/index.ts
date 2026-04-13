import express from 'express';
import cors from 'cors';

const app = express();
app.use(cors());
app.use(express.json());

const REMOTE_ENTRY_URL = 'http://localhost:3004/remoteEntry.js';

app.get('/api/components/:name', (req, res) => {
  const { name } = req.params;
  if (name === 'EmployeeChart') {
    res.json({
      componentName: 'EmployeeChart',
      containerName: 'employeeChartCard',
      remoteEntryUrl: REMOTE_ENTRY_URL,
    });
  } else {
    res.status(404).json({ error: 'Component not found' });
  }
});

app.get('/health', (_req, res) => res.json({ ok: true }));

app.listen(3003, () => console.log('resource-center-mock running on :3003'));
