const express = require('express');
const cors = require('cors');
const dotenv = require('dotenv');
dotenv.config();

const app = express();
app.use(cors());
app.use(express.json());

const PORT = process.env.PORT || 4000;
const { initDb } = require('./db');
initDb();

app.use('/api/games', require('./routes/games'));

app.listen(PORT, () => {
  console.log(`Server listening on http://localhost:${PORT}`);
});
