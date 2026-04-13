import React from 'react';
import { createRoot } from 'react-dom/client';
import EmployeeChart from './EmployeeChart';

const mockData = [
  { year: 2019, count: 7000 },
  { year: 2020, count: 10000 },
  { year: 2021, count: 16000 },
  { year: 2022, count: 22000 },
  { year: 2023, count: 18000 },
];

createRoot(document.getElementById('root')!).render(
  <EmployeeChart data={mockData} token="dev-token" />
);
