import { configureStore } from '@reduxjs/toolkit';
import { renderToStaticMarkup } from 'react-dom/server';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import preferenceReducer, { setRoles } from '../preferences/preferenceSlice';
import AdminRoute from './AdminRoute';

function renderWith(roles: string[] | null) {
  const store = configureStore({ reducer: { preference: preferenceReducer } });
  if (roles !== null) store.dispatch(setRoles(roles));
  return renderToStaticMarkup(
    <Provider store={store}>
      <MemoryRouter>
        <AdminRoute>
          <div>admin-secret</div>
        </AdminRoute>
      </MemoryRouter>
    </Provider>,
  );
}

describe('AdminRoute', () => {
  it('hides content until roles are resolved', () => {
    expect(renderWith(null)).not.toContain('admin-secret');
  });

  it('redirects (renders nothing) for non-admins', () => {
    expect(renderWith(['user'])).not.toContain('admin-secret');
  });

  it('renders children for admins', () => {
    expect(renderWith(['admin', 'user'])).toContain('admin-secret');
  });
});
