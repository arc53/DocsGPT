// When testing library added this is unit test for the useMediaQuery

// import { renderHook } from '@testing-library/react-hooks';
// import { useMediaQuery } from '.';

// describe('useMediaQuery', () => {
//     it('should update isMobile and isDesktop when window is resized', () => {
//         const { result } = renderHook(() => useMediaQuery());

//         global.innerWidth = 800;
//         global.dispatchEvent(new Event('resize'));
//         expect(result.current.isMobile).toBe(true);
//         expect(result.current.isDesktop).toBe(false);

//         global.innerWidth = 1200;
//         global.dispatchEvent(new Event('resize'));
//         expect(result.current.isMobile).toBe(false);
//         expect(result.current.isDesktop).toBe(true);
//     });
// });
