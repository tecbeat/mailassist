import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docsSidebar: [
    'index',
    {
      type: 'category',
      label: 'Getting Started',
      items: [
        'getting-started/installation',
        'getting-started/configuration',
        'getting-started/first-run',
      ],
    },
    {
      type: 'category',
      label: 'Concepts',
      items: [
        'concepts/architecture',
        'concepts/pipeline',
        'concepts/encryption',
      ],
    },
    {
      type: 'category',
      label: 'Plugins',
      items: [
        'plugins/index',
        'plugins/rules',
        'plugins/spam',
        'plugins/newsletters',
        'plugins/labeling',
        'plugins/smart-folders',
        'plugins/coupons',
        'plugins/calendar',
        'plugins/auto-reply',
        'plugins/summary',
        'plugins/contacts',
        'plugins/notifications',
      ],
    },
    {
      type: 'category',
      label: 'Operations',
      items: [
        'operations/backup',
        'operations/upgrading',
        'operations/key-rotation',
        'operations/monitoring',
        'operations/troubleshooting',
      ],
    },
  ],
};

export default sidebars;
