-- Fictional sample registry. These funds do not exist.
CREATE TABLE funds (
    isin TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE authorisations (
    isin TEXT NOT NULL REFERENCES funds (isin),
    country TEXT NOT NULL,
    PRIMARY KEY (isin, country)
);

INSERT INTO funds (isin, name) VALUES
    ('FRCOPS000017', 'Sample Global Equity Fund'),
    ('LUCOPS000022', 'Sample Sustainable Bond Fund'),
    ('FRCOPS000033', 'Sample French Small Cap Fund');

INSERT INTO authorisations (isin, country) VALUES
    ('FRCOPS000017', 'FR'),
    ('FRCOPS000017', 'DE'),
    ('LUCOPS000022', 'LU'),
    ('LUCOPS000022', 'FR'),
    ('FRCOPS000033', 'FR');
