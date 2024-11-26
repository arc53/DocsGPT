export const getOS = () => {
    const platform = window.navigator.platform;
    const userAgent = window.navigator.userAgent || window.navigator.vendor;
  
    if (/Mac/i.test(platform)) {
      return 'mac';
    }
  
    if (/Win/i.test(platform)) {
      return 'win';
    }
  
    if (/Linux/i.test(platform) && !/Android/i.test(userAgent)) {
      return 'linux';
    }
  
    if (/Android/i.test(userAgent)) {
      return 'android';
    }
  
    if (/iPhone|iPad|iPod/i.test(userAgent)) {
      return 'ios';
    }
  
    return 'other';
  };
  