export const randomString = (len: number) => { 
    return Math.random().toString(36).substring(2, len + 2);
}

export const getCurrentTime = () => { 
    // Asia/Shanghai
    return new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
}

export const getCurrentStatus = () => { 
    const currentTime = getCurrentTime()
    const currentHour = Number(currentTime.split(' ')[1].split(':')[0])
    if (currentHour >= 6 && currentHour < 12) { 
        return '上午'
    } else if (currentHour >= 12 && currentHour < 18) { 
        return '下午'
    } else { 
        return '晚上'
    }
}

// 获取格式化时间字符串2025-06-21T12:29:15
export const getFormatTimeString = (time:string) => {
    const date = time.split('T')[0]
    const timeString = time.split('T')[1]
    //  当年就只显示月日时间
    if (date.split('-')[0] === new Date().getFullYear().toString()) { 
        // 如果是今天，就只显示时间
        if (date === new Date().toISOString().split('T')[0]) { 
            return timeString.split('.')[0]
        }
        return `${date.split('-')[1]}-${date.split('-')[2]} ${timeString.split('.')[0]}`
    }
    return `${date} ${timeString.split('.')[0]}`
}