import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'mailassist',
  tagline: 'The self-hosted AI email assistant',
  favicon: 'img/favicon.ico',

  future: {
    v4: true,
  },

  url: 'https://tecbeat.gitlab.io',
  baseUrl: '/mailassist/',

  organizationName: 'tecbeat',
  projectName: 'mailassist',

  onBrokenLinks: 'throw',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          routeBasePath: '/',
          editUrl:
            'https://git.teccave.de/tecbeat/mailassist/-/edit/main/docs/docs/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'mailassist',
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docsSidebar',
          position: 'left',
          label: 'Documentation',
        },
        {
          href: 'https://git.teccave.de/tecbeat/mailassist',
          label: 'GitLab',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Documentation',
          items: [
            {label: 'Getting Started', to: '/getting-started/installation'},
            {label: 'Concepts', to: '/concepts/architecture'},
            {label: 'Plugins', to: '/plugins/'},
            {label: 'Operations', to: '/operations/backup'},
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} tecbeat. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'yaml', 'toml'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
